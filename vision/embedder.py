"""DINOv3 behind a two-function seam: load() once at startup, then
embed(images) → float32 vectors. Nothing else imports torch.

The weights are gated on Hugging Face under Meta's DINOv3 license and cannot
ship with this FOSS repo (D-V1): the operator accepts the license on the
model page, sets HF_TOKEN, and the first start downloads into the HF cache
(a volume in compose, so restarts don't re-download). Absent weights are a
DEGRADED state, not a crash — /health reports it and every scoring call
returns LICENSE_HELP — because the sidecar must stay up to serve stored
images and rescores, which need no model.

torch/transformers are imported inside load() so the module (and the test
suite, which stubs this seam) never pays the torch import.
"""

import logging
from io import BytesIO

import numpy as np
from config import HF_TOKEN, VISION_MODEL
from PIL import Image

log = logging.getLogger(__name__)

LICENSE_HELP = (
    f"DINOv3 weights are not loaded. They are gated under Meta's license: accept it at "
    f"https://huggingface.co/{VISION_MODEL}, create an access token at "
    f"https://huggingface.co/settings/tokens, set HF_TOKEN in vision/.env, and restart "
    f"the vision service — the first start downloads the weights."
)

_model = None
_processor = None
_dim: int | None = None


def load() -> int | None:
    """Load (downloading on first run) the model; its embedding dim, or None
    when weights are unavailable — the service then runs degraded, which is
    the designed failure mode for missing token/license/network, so the
    broad catch here surfaces through /health and LICENSE_HELP, not a log
    nobody reads."""
    global _model, _processor, _dim
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModel

        _processor = AutoImageProcessor.from_pretrained(VISION_MODEL, token=HF_TOKEN)
        _model = AutoModel.from_pretrained(VISION_MODEL, token=HF_TOKEN)
        _model.eval()
        if torch.cuda.is_available():  # GPU is a bonus, never a requirement (D-V1)
            _model = _model.to("cuda")
        _dim = _model.config.hidden_size
    except Exception as exc:
        log.error(f"DINOv3 weights unavailable, running degraded: {exc}")
        _model = _processor = _dim = None
        return None
    log.info(f"Loaded {VISION_MODEL} (dim {_dim})")
    return _dim


def loaded() -> bool:
    return _dim is not None


def embed(images: list[bytes]) -> np.ndarray:
    """Embed already-fetched image bytes; an (n, dim) float32 array of CLS
    embeddings. Only genuinely new pixels ever reach this (D-V8) — callers
    reuse stored embeddings by content hash first."""
    import torch

    assert _model is not None and _processor is not None, "embed() before successful load()"
    pil_images = [Image.open(BytesIO(data)).convert("RGB") for data in images]
    inputs = _processor(images=pil_images, return_tensors="pt").to(_model.device)
    with torch.inference_mode():
        outputs = _model(**inputs)
    pooled = outputs.pooler_output
    if pooled is None:
        pooled = outputs.last_hidden_state[:, 0]
    return pooled.cpu().numpy().astype(np.float32)
