from datetime import datetime

from sqlalchemy.orm.base import LOAD_AGAINST_COMMITTED
from config import AsyncSessionLocal
from config import Items, Sites, Listings, PriceChecks
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import Select, select, update


async def save_listing(item_id: int, site_id: int, url: str, rationale: str, confidence:float, site_sku:str|None = None) -> int|str:
    """
    This tool is used to save a listing that matches the users selected criteria to the database and generated a listing site_id
    
    Args:
      item_id: The item id you have for the current item
      site_id: The internal id for the current site being seeached
      url: The URL of the item that was found meeting the requered criteria
      site_sku: If a SKU s present on the site record it here
      confidence: How confident you are that this item is what the user wants and matches the requested criteria. Record as a decimal percentage (exmaples: .67, .04, .42, ect)
      rationale: Explain why you belive this item matches the requested criteria and back up your confidence score 
    Return:
      This tool returns one of these two:
        listing_id: The internal ID for the listing we just made. If it exsists already will get the exsisting item_id
        Error: A string showing the site/item combo the errored out and what the error is
    """
    async with AsyncSessionLocal() as session:
        try:
            stmt = insert(Listings).values(
                item_id=item_id,
                site_id=site_id,
                url=url,
                site_sku=site_sku,
                active=True,
                rationale=rationale,
                confidence=confidence
            ).on_conflict_do_nothing(constraint='uq_site_url')

            await session.execute(stmt)
            await session.commit()

            stmt = select(Listings).where(
              Listings.item_id == item_id,
              Listings.site_id == site_id,
              Listings.url == url,
              Listings.active == True
            ).limit(1)

            results = await session.execute(stmt)
            listing_id  = results.scalar()            
            if listing_id is not None:      
                return int(listing_id.id)
            else:
                return f"Unable to fetch the listing id for the item {item_id} on site {site_id}"
        except Exception as e:
          return f"Error recording listing for item {item_id} on site {site_id}: {e}"


    
async def save_price_check(listing_id: int, price: float, in_stock: bool, status: str, currency: str = "USD") -> str:
    """
    Use this tool after a listing is create for a item meeting the crieteriae3
    """

    async with AsyncSessionLocal() as session:
        try:
            stmt = insert(PriceChecks).values(
                listing_id=listing_id,
                price=price,
                currency=currency,
                in_stock=in_stock,
                status=status,
                created_at=datetime.now
            )    

            await session.execute(stmt)
            await session.commit(   )

            return f"Successfully recorded listing {listing_id}"


        except Exception as e:
            return f"Error inserting price check for listing {listing_id}: {e}"


    
