from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, Date

Base = declarative_base()

class CarListing(Base):
    __tablename__ = 'cars'
    id = Column(Integer, primary_key=True)
    listing = Column(String)
    link = Column(String, unique=True)
    mileage = Column(String)
    price = Column(String)
    is_hybrid = Column(Boolean)
    date_found = Column(Date)
