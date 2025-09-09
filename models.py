from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, Date
from datetime import date

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
    still_available = Column(Boolean, default=True)
    year = Column(String)  # Add year field
    manual_price = Column(Boolean, default=False)  # Track manual price entries
    
    @property
    def days_listed(self):
        """Calculate days since listing was found"""
        if self.date_found:
            return (date.today() - self.date_found).days
        return 0
