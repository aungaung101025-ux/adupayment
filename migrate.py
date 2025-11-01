# migrate.py
# (!!!) ဒီ script ကို (၁) ကြိမ်သာ run ရန်။
# (!!!) run မလုပ်ခင် `user_data.json` နှင့် `secret.key` ကို back up လုပ်ပါ။

import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import datetime as dt

# --- DataManager အဟောင်း (JSON + Encryption) ---
try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    print("Migration script needs 'cryptography'. Please run: pip install cryptography")
    sys.exit(1)

USER_DATA_FILE = 'user_data.json'
ENCRYPTION_KEY_FILE = 'secret.key'
logger = logging.getLogger(__name__)

class OldDataManager:
    def __init__(self, file_path: str, key_file: str):
        if not os.path.exists(key_file):
            print(f"FATAL: {key_file} not found. Cannot decrypt old data.")
            sys.exit(1)
            
        self.file_path = file_path
        self.key_file = key_file
        self.key = self._load_or_generate_key()
        self.fern_obj = Fernet(self.key)
        self.data: Dict[str, Any] = self._load_data()
        print("Old DataManager loaded.")

    def _load_or_generate_key(self) -> bytes:
        if os.path.exists(self.key_file):
            with open(self.key_file, 'rb') as f:
                key = f.read()
            logger.info("Encryption key loaded successfully.")
        else:
            raise FileNotFoundError(f"{self.key_file} not found. Cannot decrypt old data.")
        return key

    def _load_data(self) -> Dict[str, Any]:
        if not os.path.exists(self.file_path):
            print(f"WARNING: {self.file_path} not found. No data to migrate.")
            return {}
        
        try:
            with open(self.file_path, 'rb') as f:
                encrypted_data = f.read()
            
            if not encrypted_data:
                return {}

            try:
                decrypted_data = self.fern_obj.decrypt(encrypted_data)
                return json.loads(decrypted_data.decode('utf-8'))
            
            except InvalidToken:
                logger.warning("InvalidToken: Data may not be encrypted. Attempting to migrate...")
                try:
                    data_str = encrypted_data.decode('utf-8')
                    data = json.loads(data_str)
                    logger.info("Successfully loaded unencrypted data.")
                    return data
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.error("Failed to migrate unencrypted data. File might be corrupt.")
                    return {}
                    
        except IOError as e:
            logger.error(f"Error loading data file: {e}")
            return {}
            
    def get_all_data(self):
        return self.data

# --- DataManager အသစ် (Database) ---
from sqlalchemy.orm import sessionmaker
from models import User, Transaction, Budget, Goal, CustomCategory, RecurringTx, engine, Base, SessionLocal
import uuid

def parse_date(date_str):
    """Safely parse ISO date strings."""
    if not date_str:
        return datetime.min
    try:
        if '.' in date_str and ('+' in date_str or 'Z' in date_str):
            return datetime.fromisoformat(date_str)
        elif '.' in date_str:
            return datetime.strptime(date_str.split('.')[0], "%Y-%m-%dT%H:%M:%S")
        else:
            return datetime.fromisoformat(date_str.split('+')[0])
    except Exception as e:
        print(f"Date parse error for '{date_str}': {e}. Using fallback.")
        return datetime.min # Fallback

def run_migration():
    print("Starting migration...")
    
    # 1. Load old data from JSON
    try:
        old_manager = OldDataManager(USER_DATA_FILE, ENCRYPTION_KEY_FILE)
        old_data = old_manager.get_all_data()
    except Exception as e:
        print(f"Could not load old data. Is '{ENCRYPTION_KEY_FILE}' present? Error: {e}")
        return
        
    if not old_data:
        print("Old data file is empty or cannot be read. Aborting.")
        return

    # 2. Setup new database
    Base.metadata.create_all(engine)
    session = SessionLocal()

    print(f"Found {len(old_data)} users in old data file.")
    
    # 3. Loop and insert
    migrated_users = 0
    try:
        for user_id_str, user_data in old_data.items():
            try:
                user_id = int(user_id_str)
            except ValueError:
                print(f"Skipping invalid user_id: {user_id_str}")
                continue
                
            # Check if user already exists
            existing_user = session.query(User).filter_by(id=user_id).first()
            if existing_user:
                print(f"User {user_id} already exists in database. Skipping to avoid duplicates.")
                continue

            print(f"Migrating user {user_id}...")
            
            # --- Create User ---
            premium_info = user_data.get('premium', {})
            settings = user_data.get('settings', {}).get('reminders', {})
            
            new_user = User(
                id=user_id,
                premium_is_premium=premium_info.get('is_premium', False),
                premium_end_date=parse_date(premium_info.get('end_date', datetime.min.isoformat())),
                premium_used_trial=premium_info.get('used_trial', False),
                settings_daily_reminder=settings.get('daily_transaction', False),
                settings_weekly_day=settings.get('weekly_day', 'Sunday'),
                settings_weekly_summary=settings.get('weekly_summary', False)
            )
            session.add(new_user)
            
            # --- Transactions ---
            for tx in user_data.get('transactions', []):
                new_tx = Transaction(
                    id=tx.get('id', str(uuid.uuid4())),
                    date=parse_date(tx.get('date', datetime.now().isoformat())),
                    type=tx.get('type'),
                    amount=tx.get('amount'),
                    description=tx.get('description'),
                    category=tx.get('category'),
                    user_id=user_id
                )
                session.add(new_tx)

            # --- Budgets ---
            for category, amount in user_data.get('budgets', {}).items():
                new_budget = Budget(category=category, amount=amount, user_id=user_id)
                session.add(new_budget)

            # --- Goals ---
            for goal_id, goal in user_data.get('goals', {}).items():
                new_goal = Goal(
                    id=goal.get('id', goal_id),
                    name=goal.get('name'),
                    target_amount=goal.get('target_amount'),
                    target_date=parse_date(goal.get('target_date', datetime.now().isoformat())),
                    start_date=parse_date(goal.get('start_date', datetime.now().isoformat())),
                    user_id=user_id
                )
                session.add(new_goal)

            # --- Custom Categories ---
            for cat_type, names in user_data.get('custom_categories', {}).items():
                for name in names:
                    new_cat = CustomCategory(type=cat_type, name=name, user_id=user_id)
                    session.add(new_cat)

            # --- Recurring Txs ---
            for rtx in user_data.get('recurring_tx', []):
                new_rtx = RecurringTx(
                    id=rtx.get('id', str(uuid.uuid4())),
                    type=rtx.get('type'),
                    amount=rtx.get('amount'),
                    description=rtx.get('description'),
                    category=rtx.get('category'),
                    day=rtx.get('day'),
                    user_id=user_id
                )
                session.add(new_rtx)
            
            migrated_users += 1
            
        session.commit()
        print(f"Successfully migrated {migrated_users} new users.")

    except Exception as e:
        print(f"An error occurred: {e}. Rolling back...")
        session.rollback()
    finally:
        session.close()
        print("Migration script finished.")

if __name__ == "__main__":
    if not os.path.exists(ENCRYPTION_KEY_FILE):
        print(f"FATAL: '{ENCRYPTION_KEY_FILE}' not found.")
        print("Please place your encryption key in the same directory to decrypt old data.")
        sys.exit(1)
        
    if not os.path.exists(USER_DATA_FILE):
        print(f"WARNING: '{USER_DATA_FILE}' not found. No data to migrate.")
        sys.exit(0)

    if os.path.exists('financebot.db'):
        print("WARNING: 'financebot.db' already exists.")
        print("This script will ONLY add new users from 'user_data.json' that are not already in the database.")
        confirm = input("Are you sure you want to continue? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)
    
    run_migration()