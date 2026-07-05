from sqlalchemy.orm import query_expression



async def generate_prompt(site_id: int, site_text: str, item_id: int, item_name: str) -> str:
    """
    This function takes in the needed data to generate a prompt for one item
    
    args:
        site_id: ID of the current site being searched.
        site_name: Name of the site currently being searched.
        item_id: ID of the current item being searched for.
        item_name: Name of the item currently brring searched for.

    return:
        str: The prompt for the LLM agent
    """

    return ""

