"""The item <-> watch <-> watch_sites mapping. The one genuinely fiddly bit of
CRUD in the whole backend, so it gets its own module (keeps routers/items.py thin).

Responsibilities:
  - create_item(): find-or-create shared items row + create the caller's watch
    + insert watch_sites; validate site_ids is a subset of the category's sites
    (422 otherwise); normalize empty/full set -> null.
  - update_item()/update_watch(): write back to items vs watches correctly.
  - serialize_item_summary()/serialize_item_detail(): join watch + rollups
    (from services/aggregates.py) into the ItemSummary/ItemDetail shape.
  - list_items(): scope to the current user's watches + apply ItemListParams filters.

Validation rules (match mocks/handlers.ts):
  - selection_mode in {'cheapest','best_match'} else 422 validation_error
  - max_listings in 1..10 else 422 validation_error
  - site_ids ⊄ category sites -> 422 validation_error
"""

# TODO: implement the functions described above.
