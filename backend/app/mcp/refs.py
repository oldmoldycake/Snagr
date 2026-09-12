"""Resolving the loose references agents hold. An agent rarely has an id in
hand — it has "cameras" or "eBay" — so category arguments accept an id or a
slug (or the name) and site arguments an id or a name. Unknown → 404 like
REST; a name shared by several sites → 422 naming the candidates, because
guessing would act on the wrong one."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import err
from app.models import Categories, Sites

Ref = int | str


def _as_id(ref: Ref) -> int | None:
    """An int, or a string that is only digits, is an id; anything else a name."""
    if isinstance(ref, int):
        return ref
    return int(ref) if ref.strip().isdigit() else None


async def resolve_category(db: AsyncSession, ref: Ref) -> Categories:
    if (category_id := _as_id(ref)) is not None:
        category = await db.get(Categories, category_id)
    else:
        key = ref.strip().lower()
        category = await db.scalar(
            select(Categories).where(
                or_(Categories.slug == key, func.lower(Categories.name) == key)
            )
        )
    if category is None:
        raise err(404, "not_found", f"Category {ref!r} does not exist")
    return category


async def resolve_site(db: AsyncSession, ref: Ref) -> Sites:
    if (site_id := _as_id(ref)) is not None:
        site = await db.get(Sites, site_id)
    else:
        matches = (
            await db.scalars(
                select(Sites)
                .where(func.lower(Sites.name) == ref.strip().lower())
                .order_by(Sites.id)
            )
        ).all()
        if len(matches) > 1:
            candidates = ", ".join(f"{s.id} ({s.base_url})" for s in matches)
            raise err(
                422,
                "validation_error",
                f"Several sites are named {ref!r} — use an id: {candidates}",
                fields={"site": "Ambiguous name"},
            )
        site = matches[0] if matches else None
    if site is None:
        raise err(404, "not_found", f"Site {ref!r} does not exist")
    return site
