from decimal import Decimal
import os
from dotenv import load_dotenv
import sqlalchemy
from sqlalchemy.sql.functions import current_timestamp
from sqlalchemy.util import concurrency

load_dotenv()


#Database
from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint, Numeric, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Session, mapped_column, Mapped
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")
assert DATABASE_URL is not None, "DATABASE_URL environment varable is not set"
engine = create_engine(
    url=sqlalchemy.engine.make_url(DATABASE_URL),
    pool_size=5,    
    echo=False
)
    
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    email:          Mapped[str]         = mapped_column(Text, unique=True)
    email_verified: Mapped[bool]        = mapped_column(Boolean, default=False)
    created_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

class Sites(Base):
    __tablename__ = "sites"
    
    id:             Mapped[int]         = mapped_column(primary_key=True)
    name:           Mapped[str]         = mapped_column(Text, nullable=False)
    base_url:       Mapped[str]         = mapped_column(Text, nullable=False)
    created_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now()) 


class Items(Base):
    __tablename__ = "items"
     
    id:             Mapped[int]         = mapped_column(primary_key=True)
    name:           Mapped[str]         = mapped_column(Text, nullable=False)
    target_price:   Mapped[float|None]  = mapped_column(Numeric(precision=10, scale=2))
    created_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

class Listings(Base):
    __tablename__ = "listings"

    id:             Mapped[int]         = mapped_column(primary_key=True)   
    item_id:        Mapped[int]         = mapped_column(ForeignKey("items.id"))
    site_id:        Mapped[int]         = mapped_column(ForeignKey("sites.id"))
    url:            Mapped[str]         = mapped_column(Text, nullable=False)
    site_sku:       Mapped[str|None]    = mapped_column(Text)
    active:         Mapped[bool]        = mapped_column(Boolean, default=True)
    
    __table_args__ = (
        UniqueConstraint("item_id", "site_id", name="uq_item_site")     
    )

class PriceChecks(Base):
    __tablename__ = "price_checks"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    listing_id:     Mapped[int]         = mapped_column(ForeignKey("listings.id"))
    price:          Mapped[float|None]  = mapped_column(Numeric(precision=10, scale=2))
    currency:       Mapped[str]         = mapped_column(Text, default="USD")
    in_stock:       Mapped[bool|None]   = mapped_column(Boolean)
    status:         Mapped[str|None]    = mapped_column(Text)
    checked_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True))

class Watches(Base):
    __tablename__ = "watches"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    user_id:        Mapped[int]         = mapped_column(ForeignKey("users.id"))
    item_id:        Mapped[int]         = mapped_column(ForeignKey("items.id"))
    target_price:   Mapped[float|None]  = mapped_column(Numeric(precision=10, scale=2))
    notify:         Mapped[bool]        = mapped_column(Boolean, default=True)
    created_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), current_timestamp=True)
    
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_item_user")
    )
        
#AI 
OLLAMA_URL = os.getenv("OLLAMA_URL","http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_URL","qwen3.6:34b")

#MCP
PLAYWRIGHT_MCP_URL = os.getenv("PLAYWRIGHT_MCP_URL")

