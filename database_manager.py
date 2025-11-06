# database_manager.py (UPDATED for Multi-Wallet)
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
import datetime as dt # For compatibility
from typing import Dict, List, Optional, Any, Tuple

from sqlalchemy.orm import sessionmaker, Session, joinedload
from sqlalchemy import func

# Import models and SessionLocal from models.py
# (!!!) Account, TransferLog ကို ထပ်တိုးပါ (!!!)
from models import User, Transaction, Budget, Goal, CustomCategory, RecurringTx, SessionLocal, setup_database, Account, TransferLog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Context Manager for DB Sessions ---
@contextmanager
def get_session() -> Session:
    """Provides a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.error("Database session rolled back due to error.", exc_info=True)
        raise
    finally:
        session.close()


class DatabaseManager:
    
    def __init__(self):
        """Initializes the DatabaseManager and ensures tables are created."""
        setup_database() # This creates tables if they don't exist
        logger.info("DatabaseManager initialized. Tables are ready.")

    def get_or_create_user(self, session: Session, user_id: int) -> User:
        """
        Gets a user from the DB. If not found, creates a new one.
        This replaces the old _initialize_user.
        """
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            logger.info(f"Creating new user: {user_id}")
            user = User(
                id=user_id,
                premium_is_premium=False,
                premium_end_date=datetime.min,
                premium_used_trial=False,
                settings_daily_reminder=False,
                settings_weekly_summary=False,
                settings_weekly_day='Sunday'
            )
            session.add(user)
            session.commit() # Commit immediately so user exists
        return user

    # --- (!!!) NEW: Account Management Functions (!!!) ---
    def add_account(self, user_id: int, name: str, initial_balance: int = 0) -> Tuple[Optional[Account], str]:
        """Creates a new account for the user."""
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            
            # Check if account with same name already exists
            existing = session.query(Account).filter_by(user_id=user_id, name=name).first()
            if existing:
                return None, f"❌ '{name}' အမည်ဖြင့် Account ရှိပြီးသားပါ။"
                
            new_account = Account(
                name=name,
                initial_balance=initial_balance,
                user_id=user_id
            )
            session.add(new_account)
            session.flush() # ID ကို ချက်ချင်း ရယူရန်
            
            # If initial balance is set, add an "Opening Balance" transaction
            if initial_balance != 0:
                tx_type = 'income' if initial_balance > 0 else 'expense'
                new_tx = Transaction(
                    id=str(uuid.uuid4()),
                    date=datetime.now(),
                    type=tx_type,
                    amount=abs(initial_balance),
                    description="Opening Balance",
                    category="Initial Balance",
                    user_id=user_id,
                    account_id=new_account.id # Account အသစ်နဲ့ ချိတ်ဆက်ပါ
                )
                session.add(new_tx)
            
            logger.info(f"User {user_id} created new account '{name}' with balance {initial_balance}")
            return new_account, "✅ Account အသစ်ကို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ။"

    def get_account_by_name(self, session: Session, user_id: int, name: str) -> Optional[Account]:
        """Helper to find an account by name."""
        return session.query(Account).filter_by(user_id=user_id, name=name).first()

    def get_accounts(self, user_id: int) -> List[Account]:
        """Gets all accounts for a user."""
        with get_session() as session:
            return session.query(Account).filter_by(user_id=user_id).order_by(Account.name).all()

    def calculate_account_balance(self, session: Session, account_id: str) -> int:
        """Calculates the current balance for a single account."""
        
        # 1. Initial Balance
        account = session.query(Account).filter_by(id=account_id).first()
        if not account:
            return 0
        balance = account.initial_balance
        
        # 2. Income/Expense Transactions
        incomes = session.query(func.sum(Transaction.amount)).filter_by(account_id=account_id, type='income').scalar() or 0
        expenses = session.query(func.sum(Transaction.amount)).filter_by(account_id=account_id, type='expense').scalar() or 0
        
        # 3. Transfers In/Out
        transfers_in = session.query(func.sum(TransferLog.amount)).filter_by(to_account_id=account_id).scalar() or 0
        transfers_out = session.query(func.sum(TransferLog.amount)).filter_by(from_account_id=account_id).scalar() or 0
        
        balance = balance + incomes - expenses + transfers_in - transfers_out
        return int(balance) # Ensure it returns integer

    def get_accounts_with_balance(self, user_id: int) -> List[Dict[str, Any]]:
        """Gets all accounts and their calculated balances."""
        with get_session() as session:
            accounts = session.query(Account).filter_by(user_id=user_id).order_by(Account.name).all()
            result = []
            for acc in accounts:
                result.append({
                    "id": acc.id,
                    "name": acc.name,
                    "balance": self.calculate_account_balance(session, acc.id)
                })
            return result
    # --- (!!!) End of New Account Functions (!!!) ---

    # --- NEW: Get all user IDs for schedulers ---
    def get_all_users_for_reminders(self) -> List[Tuple[int, bool, str, bool]]:
        """
        Fetches all users who need reminders (Premium only).
        Returns list of (user_id, daily_on, weekly_day, weekly_on)
        """
        with get_session() as session:
            users = session.query(User).filter(
                User.premium_is_premium == True,
                User.premium_end_date > datetime.now(),
                (User.settings_daily_reminder == True) | (User.settings_weekly_summary == True)
            ).all()
            
            return [(u.id, u.settings_daily_reminder, u.settings_weekly_day, u.settings_weekly_summary) for u in users]

    def get_all_users_for_recurring_tx(self) -> List[int]:
        """Fetches all users who have recurring TX (Premium only)."""
        with get_session() as session:
            users = session.query(User.id).filter(
                User.premium_is_premium == True,
                User.premium_end_date > datetime.now()
            ).join(User.recurring_txs).distinct().all()
            
            return [u[0] for u in users] # u is a tuple (user_id,)


    # --- User Data Deletion ---
    def delete_user_data(self, user_id: int) -> bool:
        """Deletes a user and all their related data (cascade)."""
        with get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if user:
                session.delete(user)
                logger.info(f"Deleted all data for user {user_id}")
                return True
            return False

    # --- Premium Methods ---
    
    def get_premium_status(self, user_id: int) -> Dict[str, Any]:
        """Gets premium status from the User table."""
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            
            is_premium = user.premium_is_premium and (user.premium_end_date > datetime.now())
            
            if user.premium_is_premium and not is_premium:
                # Premium expired, update it
                user.premium_is_premium = False
                logger.info(f"Premium expired for user {user_id}")
            
            return {
                'is_premium': is_premium,
                'end_date': user.premium_end_date.strftime('%Y-%m-%d'),
                'used_trial': user.premium_used_trial
            }

    def grant_premium(self, user_id: int, days: int, is_trial: bool = False):
        """Grants premium access by updating the User table."""
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            
            end_date = datetime.now() + timedelta(days=days)
            user.premium_is_premium = True
            user.premium_end_date = end_date
            if is_trial:
                user.premium_used_trial = True
            
            logger.info(f"Granted premium to {user_id} for {days} days.")
            return end_date.strftime('%Y-%m-%d')
            
    # --- Custom Category Methods ---
    def get_custom_categories(self, user_id: int, type: str) -> List[str]:
        with get_session() as session:
            cats = session.query(CustomCategory.name).filter_by(user_id=user_id, type=type).all()
            return [c.name for c in cats]

    def add_custom_category(self, user_id: int, type: str, category_name: str) -> bool:
        with get_session() as session:
            user = self.get_or_create_user(session, user_id) # Ensure user exists
            category_name = category_name.strip()
            
            exists = session.query(CustomCategory).filter_by(user_id=user_id, type=type, name=category_name).first()
            if not exists:
                new_cat = CustomCategory(user_id=user_id, type=type, name=category_name)
                session.add(new_cat)
                return True
            return False

    def remove_custom_category(self, user_id: int, type: str, category_name: str) -> bool:
        with get_session() as session:
            cat = session.query(CustomCategory).filter_by(user_id=user_id, type=type, name=category_name).first()
            if cat:
                session.delete(cat)
                return True
            return False

    # --- Goal Tracking Methods ---
    def add_goal(self, user_id: int, name: str, amount: int, target_date: datetime):
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            new_goal = Goal(
                id=str(uuid.uuid4()),
                name=name.strip(),
                target_amount=amount,
                target_date=target_date,
                start_date=datetime.now(),
                user_id=user_id
            )
            session.add(new_goal)
            return new_goal.id

    def get_all_goals(self, user_id: int) -> List[Dict[str, Any]]:
        with get_session() as session:
            goals = session.query(Goal).filter_by(user_id=user_id).all()
            return [g.to_dict() for g in goals] # Use helper

    def delete_goal(self, user_id: int, goal_id: str) -> bool:
        with get_session() as session:
            goal = session.query(Goal).filter_by(user_id=user_id, id=goal_id).first()
            if goal:
                session.delete(goal)
                return True
            return False

    def calculate_goal_progress(self, user_id: int) -> List[Dict[str, Any]]:
        with get_session() as session:
            goals = session.query(Goal).filter_by(user_id=user_id).all()
            
            # (!!!) Calculate current balance (NEW LOGIC) (!!!)
            # လက်ကျန်ငွေဆိုတာ Account အားလုံးထဲက စုစုပေါင်း ပိုက်ဆံ ဖြစ်ရပါမယ်
            all_accounts = self.get_accounts_with_balance(user_id)
            current_balance = sum(acc['balance'] for acc in all_accounts)
            
            # (!!!) Account မရှိသေးတဲ့ User အဟောင်းတွေအတွက်၊ Transaction အဟောင်းတွေကိုလည်း ထည့်တွက်ပါ (!!!)
            unassigned_income = session.query(func.sum(Transaction.amount)).filter_by(user_id=user_id, type='income', account_id=None).scalar() or 0
            unassigned_expense = session.query(func.sum(Transaction.amount)).filter_by(user_id=user_id, type='expense', account_id=None).scalar() or 0
            current_balance += (unassigned_income - unassigned_expense)
            
            progress_list = []
            for goal in goals:
                target_amount = goal.target_amount
                current_savings = max(0, min(current_balance, target_amount))
                remaining = target_amount - current_savings
                progress = (current_savings / target_amount * 100) if target_amount > 0 else 0
                emoji = "🎉" if progress >= 100 else "⏳"
                
                progress_list.append({
                    'id': goal.id,
                    'name': goal.name,
                    'target_amount': target_amount,
                    'target_date': goal.target_date.strftime('%m/%d/%Y'),
                    'current_savings': current_savings,
                    'remaining': remaining,
                    'progress': progress,
                    'emoji': emoji
                })
            return progress_list

    # --- Transaction Management Methods ---
    
    # (!!!) MODIFIED: add_transaction (!!!)
    def add_transaction(self, user_id: int, type: str, amount: int, description: str, category: str, account_id: Optional[str] = None):
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            
            # (!!!) Account ID ကိုပါ ထည့်သွင်းပါ (!!!)
            new_tx = Transaction(
                id=str(uuid.uuid4()),
                date=datetime.now(),
                type=type,
                amount=amount,
                description=description,
                category=category,
                user_id=user_id,
                account_id=account_id # <-- (!!!) ဒီလိုင်း အသစ် ထပ်တိုးပါ (!!!)
            )
            session.add(new_tx)

    # --- (!!!) NEW: Transfer Function (!!!) ---
    def add_transfer(self, user_id: int, from_account_id: str, to_account_id: str, amount: int, description: str) -> bool:
        """Logs a transfer between two accounts."""
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            
            # Check if accounts exist
            from_acc = session.query(Account).filter_by(id=from_account_id, user_id=user_id).first()
            to_acc = session.query(Account).filter_by(id=to_account_id, user_id=user_id).first()
            
            if not from_acc or not to_acc:
                logger.warning(f"Transfer failed: Account not found for user {user_id}")
                return False
                
            new_transfer = TransferLog(
                user_id=user_id,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                amount=amount,
                description=description
            )
            session.add(new_transfer)
            logger.info(f"User {user_id} transferred {amount} from {from_acc.name} to {to_acc.name}")
            return True
    # --- (!!!) End of New Transfer Function (!!!) ---

    def get_transaction_by_id(self, user_id: int, tx_id: str) -> Optional[Dict[str, Any]]:
        with get_session() as session:
            tx = session.query(Transaction).filter_by(user_id=user_id, id=tx_id).first()
            return tx.to_dict() if tx else None
        
    def get_recent_transactions(self, user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        with get_session() as session:
            txs = session.query(Transaction).filter_by(user_id=user_id).order_by(Transaction.date.desc()).limit(limit).all()
            return [tx.to_dict() for tx in txs]
        
    def delete_transaction(self, user_id: int, tx_id: str) -> bool:
        with get_session() as session:
            tx = session.query(Transaction).filter_by(user_id=user_id, id=tx_id).first()
            if tx:
                session.delete(tx)
                return True
            return False

    def update_transaction(self, user_id: int, tx_id: str, new_type: str, new_amount: int, new_description: str, new_category: str) -> Optional[Dict[str, Any]]:
        with get_session() as session:
            tx = session.query(Transaction).filter_by(user_id=user_id, id=tx_id).first()
            if tx:
                tx.type = new_type
                tx.amount = new_amount
                tx.description = new_description
                tx.category = new_category
                # Note: This doesn't update the account_id. We'd need more logic in the bot to handle that.
                return tx.to_dict()
            return None
        
    def get_all_categories(self, user_id: int, type: str, default_cats: List[str]) -> List[str]:
        custom_cats = self.get_custom_categories(user_id, type)
        return default_cats + custom_cats

    def get_transactions(self, user_id: int, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        with get_session() as session:
            query = session.query(Transaction).filter_by(user_id=user_id)
            
            if start_date is not None and end_date is None:
                # Monthly report (start_date is first of month)
                if start_date.month == 12:
                    month_end = start_date.replace(year=start_date.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    month_end = start_date.replace(month=start_date.month + 1, day=1) - timedelta(days=1)
                
                query = query.filter(Transaction.date >= start_date.replace(hour=0, minute=0), 
                                     Transaction.date <= month_end.replace(hour=23, minute=59))
                                     
            elif start_date is not None and end_date is not None:
                # Custom date range
                query = query.filter(Transaction.date >= start_date.replace(hour=0, minute=0), 
                                     Transaction.date <= end_date.replace(hour=23, minute=59))
            
            transactions = query.order_by(Transaction.date.asc()).all()
            return [tx.to_dict() for tx in transactions]

    # --- Budget Methods ---
    def set_budget(self, user_id: int, category: str, amount: int):
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            existing_budget = session.query(Budget).filter_by(user_id=user_id, category=category).first()
            if existing_budget:
                existing_budget.amount = amount
            else:
                new_budget = Budget(user_id=user_id, category=category, amount=amount)
                session.add(new_budget)

    def get_budgets(self, user_id: int) -> Dict[str, int]:
        with get_session() as session:
            budgets = session.query(Budget).filter_by(user_id=user_id).all()
            return {b.category: b.amount for b in budgets}

    # --- Reminder Methods ---
    def get_reminder_settings(self, user_id: int) -> Dict[str, Any]:
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            return {
                'weekly_summary': user.settings_weekly_summary,
                'weekly_day': user.settings_weekly_day,
                'daily_transaction': user.settings_daily_reminder
            }
            
    def set_reminder_setting(self, user_id: int, setting_name: str, value: Any):
        """
        Sets a specific reminder setting.
        setting_name can be: 'weekly_summary', 'weekly_day', 'daily_transaction'
        """
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            if setting_name == 'weekly_summary':
                user.settings_weekly_summary = value
            elif setting_name == 'weekly_day':
                user.settings_weekly_day = value
            elif setting_name == 'daily_transaction':
                user.settings_daily_reminder = value
            else:
                logger.warning(f"Unknown setting: {setting_name}")

    # --- Recurring Transaction Methods ---
    def add_recurring_tx(self, user_id: int, type: str, amount: int, description: str, category: str, day_of_month: int) -> str:
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            new_rtx = RecurringTx(
                id=str(uuid.uuid4()),
                type=type,
                amount=amount,
                description=description,
                category=category,
                day=day_of_month,
                user_id=user_id
            )
            session.add(new_rtx)
            return new_rtx.id

    def get_recurring_txs(self, user_id: int) -> List[Dict[str, Any]]:
        with get_session() as session:
            rtxs = session.query(RecurringTx).filter_by(user_id=user_id).all()
            return [r.to_dict() for r in rtxs]

    def delete_recurring_tx(self, user_id: int, tx_id: str) -> bool:
        with get_session() as session:
            rtx = session.query(RecurringTx).filter_by(user_id=user_id, id=tx_id).first()
            if rtx:
                session.delete(rtx)
                return True
            return False

# --- (STEP 4) NEW: Admin Dashboard Functions ---

    def get_stats(self) -> Dict[str, int]:
        """Gets basic statistics about the bot users."""
        with get_session() as session:
            total_users = session.query(func.count(User.id)).scalar()
            
            premium_users = session.query(func.count(User.id)).filter(
                User.premium_is_premium == True,
                User.premium_end_date > datetime.now()
            ).scalar()
            
            return {
                'total': total_users,
                'premium': premium_users
            }

    def get_all_user_ids(self) -> List[int]:
        """Gets all user IDs for broadcasting."""
        with get_session() as session:
            user_ids = session.query(User.id).all()
            return [uid[0] for uid in user_ids] # user_ids is a list of tuples like [(123,), (456,)]

    def get_user_details(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Gets detailed info for a single user."""
        with get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return None
                
            tx_count = session.query(func.count(Transaction.id)).filter_by(user_id=user_id).scalar()
            
            is_premium = user.premium_is_premium and (user.premium_end_date > datetime.now())
            
            return {
                'id': user.id,
                'is_premium': is_premium,
                'end_date': user.premium_end_date.strftime('%Y-%m-%d'),
                'used_trial': user.premium_used_trial,
                'tx_count': tx_count
            }
            
    def revoke_premium(self, user_id: int) -> bool:
        """Manually revokes a user's premium status."""
        with get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if user:
                user.premium_is_premium = False
                user.premium_end_date = datetime.min
                logger.info(f"Admin revoked premium for user {user_id}")
                return True
            return False
# --- (STEP 5) NEW: AI Financial Analyst Function ---

    def get_financial_analysis_data(self, user_id: int) -> Dict[str, Any]:
        """
        Fetches all necessary data for the AI Financial Analyst
        (past 30 days).
        """
        with get_session() as session:
            user = self.get_or_create_user(session, user_id)
            if not user:
                return {} # User မရှိရင် data မရှိပါ

            # ၁။ ရက် ၃၀ သတ်မှတ်ပါ
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)

            # ၂။ ရက် ၃၀ အတွင်း ဝင်ငွေ/ထွက်ငွေ စုစုပေါင်း
            total_income = session.query(func.sum(Transaction.amount)).filter(
                Transaction.user_id == user_id,
                Transaction.type == 'income',
                Transaction.date.between(start_date, end_date)
            ).scalar() or 0
            
            total_expense = session.query(func.sum(Transaction.amount)).filter(
                Transaction.user_id == user_id,
                Transaction.type == 'expense',
                Transaction.date.between(start_date, end_date)
            ).scalar() or 0

            # ၃။ ရက် ၃၀ အတွင်း Category အလိုက် ထွက်ငွေ (Expense Breakdown)
            expense_breakdown_query = session.query(
                Transaction.category, 
                func.sum(Transaction.amount)
            ).filter(
                Transaction.user_id == user_id,
                Transaction.type == 'expense',
                Transaction.date.between(start_date, end_date)
            ).group_by(Transaction.category).all()
            
            expense_breakdown = {category: amount for category, amount in expense_breakdown_query}

            # ၄။ သတ်မှတ်ထားသော ဘတ်ဂျက်များ
            budgets_query = session.query(Budget).filter_by(user_id=user_id).all()
            budgets = {b.category: b.amount for b in budgets_query}
            
            return {
                "total_income": total_income,
                "total_expense": total_expense,
                "expense_breakdown": expense_breakdown,
                "budgets": budgets,
                "start_date": start_date,
                "end_date": end_date
            }
# --- (STEP 6) NEW: Backup & Restore Functions ---

    def _parse_iso_date_helper(self, date_str: Optional[str]) -> Optional[datetime]:
        """Helper to safely parse ISO date strings from JSON backup."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    # (!!!) MODIFIED: get_all_data_for_backup (!!!)
    def get_all_data_for_backup(self, user_id: int) -> Dict[str, List[Dict]]:
        """Fetches all user data for creating a backup JSON file."""
        with get_session() as session:
            # Data တွေကို .to_dict() helper သုံးပြီး dict list တွေအဖြစ် ယူပါ
            transactions = [tx.to_dict() for tx in session.query(Transaction).filter_by(user_id=user_id).all()]
            goals = [g.to_dict() for g in session.query(Goal).filter_by(user_id=user_id).all()]
            recurring_txs = [r.to_dict() for r in session.query(RecurringTx).filter_by(user_id=user_id).all()]
            
            # (!!!) NEW (!!!)
            accounts = [a.to_dict() for a in session.query(Account).filter_by(user_id=user_id).all()]
            transfers = [t.to_dict() for t in session.query(TransferLog).filter_by(user_id=user_id).all()]
            
            # ဒီ model တွေမှာ .to_dict() helper မရှိလို့၊ manual လုပ်ပါ
            budgets_query = session.query(Budget).filter_by(user_id=user_id).all()
            budgets = [{"category": b.category, "amount": b.amount} for b in budgets_query]
            
            custom_cats_query = session.query(CustomCategory).filter_by(user_id=user_id).all()
            custom_categories = [{"type": c.type, "name": c.name} for c in custom_cats_query]

            return {
                "transactions": transactions,
                "budgets": budgets,
                "goals": goals,
                "custom_categories": custom_categories,
                "recurring_txs": recurring_txs,
                "accounts": accounts, # (!!!) NEW (!!!)
                "transfers": transfers # (!!!) NEW (!!!)
            }

    # (!!!) MODIFIED: restore_data_from_backup (!!!)
    def restore_data_from_backup(self, user_id: int, backup_data: Dict[str, List[Dict]]) -> bool:
        """
        Restores user data from a backup dict.
        WARNING: This DELETES all existing data for the user first.
        """
        with get_session() as session:
            # 1. --- (အရေးကြီး) Data အဟောင်းအားလုံးကို အရင်ဖျက်ပါ ---
            session.query(TransferLog).filter_by(user_id=user_id).delete() # (!!!) NEW (!!!)
            session.query(Transaction).filter_by(user_id=user_id).delete()
            session.query(Account).filter_by(user_id=user_id).delete() # (!!!) NEW (!!!)
            session.query(Budget).filter_by(user_id=user_id).delete()
            session.query(Goal).filter_by(user_id=user_id).delete()
            session.query(CustomCategory).filter_by(user_id=user_id).delete()
            session.query(RecurringTx).filter_by(user_id=user_id).delete()
            
            logger.info(f"User {user_id}: Cleared old data for restore.")

            # 2. --- Data အသစ်များ ပြန်ထည့်ပါ ---
            try:
                # (!!!) NEW: Accounts (Transactions တွေ မထည့်ခင် Account တွေ အရင်ထည့်ပါ)
                account_id_map = {} # Backup file ထဲက ID အဟောင်းနဲ့ DB ထဲက ID အသစ်ကို ချိတ်ဆက်ရန်
                for acc in backup_data.get("accounts", []):
                    old_id = acc.get('id')
                    new_acc = Account(
                        # id=old_id, # ID အဟောင်းကို မသုံးတော့ပါ၊ UUID အသစ် သုံးပါမယ်
                        name=acc.get('name'),
                        initial_balance=acc.get('initial_balance', 0), # Default to 0
                        user_id=user_id
                    )
                    session.add(new_acc)
                    session.flush() # ID အသစ်ကို ရယူရန်
                    if old_id:
                        account_id_map[old_id] = new_acc.id # ID အဟောင်း-အသစ်ကို မှတ်ထားပါ
                
                # Transactions
                for tx in backup_data.get("transactions", []):
                    old_account_id = tx.get('account_id')
                    new_account_id = account_id_map.get(old_account_id) # ID အသစ်ကို ရှာပါ
                    
                    new_tx = Transaction(
                        id=tx.get('id', str(uuid.uuid4())), # id အဟောင်းကို သုံးပါ
                        date=self._parse_iso_date_helper(tx.get('date')),
                        type=tx.get('type'),
                        amount=tx.get('amount'),
                        description=tx.get('description'),
                        category=tx.get('category'),
                        user_id=user_id,
                        account_id=new_account_id # (!!!) Account ID အသစ်ကို ထည့်ပါ (!!!)
                    )
                    session.add(new_tx)
                
                # Budgets
                for b in backup_data.get("budgets", []):
                    new_b = Budget(category=b.get('category'), amount=b.get('amount'), user_id=user_id)
                    session.add(new_b)
                    
                # Goals
                for g in backup_data.get("goals", []):
                    new_g = Goal(
                        id=g.get('id', str(uuid.uuid4())),
                        name=g.get('name'),
                        target_amount=g.get('target_amount'),
                        target_date=self._parse_iso_date_helper(g.get('target_date')),
                        start_date=self._parse_iso_date_helper(g.get('start_date')),
                        user_id=user_id
                    )
                    session.add(new_g)
                
                # Custom Categories
                for c in backup_data.get("custom_categories", []):
                    new_c = CustomCategory(type=c.get('type'), name=c.get('name'), user_id=user_id)
                    session.add(new_c)
                    
                # Recurring Txs
                for r in backup_data.get("recurring_txs", []):
                    new_r = RecurringTx(
                        id=r.get('id', str(uuid.uuid4())),
                        type=r.get('type'),
                        amount=r.get('amount'),
                        description=r.get('description'),
                        category=r.get('category'),
                        day=r.get('day'),
                        user_id=user_id
                    )
                    session.add(new_r)
                
                # (!!!) NEW: Transfers
                for t in backup_data.get("transfers", []):
                    old_from_id = t.get('from_account_id')
                    old_to_id = t.get('to_account_id')
                    
                    new_from_id = account_id_map.get(old_from_id)
                    new_to_id = account_id_map.get(old_to_id)
                    
                    if new_from_id and new_to_id: # Account ID တွေ မှန်မှ ထည့်ပါ
                        new_t = TransferLog(
                            id=t.get('id', str(uuid.uuid4())),
                            date=self._parse_iso_date_helper(t.get('date')),
                            amount=t.get('amount'),
                            description=t.get('description'),
                            user_id=user_id,
                            from_account_id=new_from_id,
                            to_account_id=new_to_id
                        )
                        session.add(new_t)

                logger.info(f"User {user_id}: Successfully restored data from backup.")
                return True
                
            except Exception as e:
                logger.error(f"Error during restore for user {user_id}: {e}")
                session.rollback() # (!!!) အမှားရှိရင် အားလုံးကို ပြန်ဖျက်ပါ
                return False