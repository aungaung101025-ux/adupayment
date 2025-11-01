# models.py
import os
import uuid
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, sessionmaker, declarative_base

# --- Base and Engine Setup ---
# Data တွေကို Render ရဲ့ Persistent Disk ထဲမှာ သိမ်းပါမယ်
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
DATABASE_URL = f"sqlite:///{DATA_DIR}/financebot.db"
engine = create_engine(DATABASE_URL)
Base = declarative_base()

# --- Helper function for converting objects to dictionaries ---
class BaseMixin:
    def to_dict(self):
        """Converts SQLAlchemy object to a dictionary."""
        # This helper is needed for get_transactions() to return dicts for pandas
        cols = {}
        for c in self.__table__.columns:
            val = getattr(self, c.name)
            if isinstance(val, datetime):
                # Convert datetime to ISO string to avoid issues
                cols[c.name] = val.isoformat()
            else:
                cols[c.name] = val
        return cols

# --- Table Definitions ---

class User(Base):
    """ Telegram User """
    __tablename__ = 'user'
    
    id = Column(Integer, primary_key=True) # Telegram User ID
    
    # Premium Status
    premium_is_premium = Column(Boolean, default=False)
    premium_end_date = Column(DateTime, default=lambda: datetime.min)
    premium_used_trial = Column(Boolean, default=False)
    
    # Settings
    settings_daily_reminder = Column(Boolean, default=False)
    settings_weekly_day = Column(String, default='Sunday')
    settings_weekly_summary = Column(Boolean, default=False)

    # Relationships
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    budgets = relationship("Budget", back_populates="user", cascade="all, delete-orphan")
    goals = relationship("Goal", back_populates="user", cascade="all, delete-orphan")
    custom_categories = relationship("CustomCategory", back_populates="user", cascade="all, delete-orphan")
    recurring_txs = relationship("RecurringTx", back_populates="user", cascade="all, delete-orphan")

class Transaction(Base, BaseMixin):
    """ User's Transaction """
    __tablename__ = 'transaction'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    date = Column(DateTime, default=datetime.now)
    type = Column(String(10)) # 'income' or 'expense'
    amount = Column(Integer)
    description = Column(String)
    category = Column(String)
    
    user_id = Column(Integer, ForeignKey('user.id'))
    user = relationship("User", back_populates="transactions")

class Budget(Base):
    """ User's Budget """
    __tablename__ = 'budget'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String)
    amount = Column(Integer)
    
    user_id = Column(Integer, ForeignKey('user.id'))
    user = relationship("User", back_populates="budgets")
    
    __table_args__ = (UniqueConstraint('user_id', 'category', name='_user_category_uc'),)

class Goal(Base, BaseMixin):
    """ User's Goal """
    __tablename__ = 'goal'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    target_amount = Column(Integer)
    target_date = Column(DateTime)
    start_date = Column(DateTime, default=datetime.now)
    
    user_id = Column(Integer, ForeignKey('user.id'))
    user = relationship("User", back_populates="goals")

class CustomCategory(Base):
    """ User's Custom Category """
    __tablename__ = 'custom_category'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(10)) # 'income' or 'expense'
    name = Column(String)
    
    user_id = Column(Integer, ForeignKey('user.id'))
    user = relationship("User", back_populates="custom_categories")

class RecurringTx(Base, BaseMixin):
    """ User's Recurring Transaction """
    __tablename__ = 'recurring_tx'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    type = Column(String(10))
    amount = Column(Integer)
    description = Column(String)
    category = Column(String)
    day = Column(Integer) # Day of month (1-28)
    
    user_id = Column(Integer, ForeignKey('user.id'))
    user = relationship("User", back_populates="recurring_txs")

# --- Initial Setup Function ---
def setup_database():
    """ Creates all tables in the engine. """
    Base.metadata.create_all(engine)

# --- Session Maker ---
SessionLocal = sessionmaker(bind=engine)

if __name__ == "__main__":
    print("Setting up database (financebot.db)...")
    setup_database()
    print("Database tables created successfully.")