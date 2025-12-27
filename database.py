import sqlite3
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name='debt_manager.db'):
        self.db_name = db_name
        self.init_database()
    
    def get_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Initialize database with required tables"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Debts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                creditor_id INTEGER NOT NULL,
                debtor_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'so''m',
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_by_creditor BOOLEAN DEFAULT FALSE,
                confirmed_by_debtor BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (creator_id) REFERENCES users(user_id),
                FOREIGN KEY (creditor_id) REFERENCES users(user_id),
                FOREIGN KEY (debtor_id) REFERENCES users(user_id)
            )
        ''')
        
        # Payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                debt_id INTEGER NOT NULL,
                payer_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (debt_id) REFERENCES debts(id),
                FOREIGN KEY (payer_id) REFERENCES users(user_id)
            )
        ''')
        
        # Groups table (for Phase 2)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                creator_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (creator_id) REFERENCES users(user_id)
            )
        ''')
        
        # Group members table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES groups(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Notifications table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                debt_id INTEGER,
                message TEXT NOT NULL,
                type TEXT NOT NULL,
                read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (debt_id) REFERENCES debts(id)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    
    def create_user(self, user_id, username, first_name, last_name):
        """Create or update user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name
        ''', (user_id, username, first_name, last_name))
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id):
        """Get user by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        conn.close()
        return dict(user) if user else None
    
    def find_user_by_username(self, username):
        """Find user by username"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Remove @ if present
        username = username.lstrip('@')
        
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        conn.close()
        return dict(user) if user else None
    
    def create_debt(self, creator_id, creditor_id, debtor_id, amount, currency, reason):
        """Create a new debt record"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO debts (creator_id, creditor_id, debtor_id, amount, currency, reason, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
        ''', (creator_id, creditor_id, debtor_id, amount, currency, reason))
        
        debt_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return debt_id
    
    def confirm_debt(self, debt_id, user_id):
        """Confirm debt by creditor or debtor"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get debt info
        cursor.execute('SELECT * FROM debts WHERE id = ?', (debt_id,))
        debt = cursor.fetchone()
        
        if not debt:
            conn.close()
            return False
        
        # Check if user is creditor or debtor
        if debt['creditor_id'] == user_id:
            cursor.execute('UPDATE debts SET confirmed_by_creditor = TRUE WHERE id = ?', (debt_id,))
        elif debt['debtor_id'] == user_id:
            cursor.execute('UPDATE debts SET confirmed_by_debtor = TRUE WHERE id = ?', (debt_id,))
        
        # Check if both confirmed
        cursor.execute('SELECT * FROM debts WHERE id = ?', (debt_id,))
        updated_debt = cursor.fetchone()
        
        if updated_debt['confirmed_by_creditor'] and updated_debt['confirmed_by_debtor']:
            cursor.execute('UPDATE debts SET status = "active" WHERE id = ?', (debt_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def get_debt(self, debt_id):
        """Get debt by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   c.first_name as creditor_name, c.username as creditor_username,
                   b.first_name as debtor_name, b.username as debtor_username,
                   cr.first_name as creator_name
            FROM debts d
            JOIN users c ON d.creditor_id = c.user_id
            JOIN users b ON d.debtor_id = b.user_id
            JOIN users cr ON d.creator_id = cr.user_id
            WHERE d.id = ?
        ''', (debt_id,))
        
        debt = cursor.fetchone()
        conn.close()
        
        return dict(debt) if debt else None
    
    def get_user_debts(self, user_id):
        """Get all debts for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   c.first_name as creditor_name, c.username as creditor_username,
                   b.first_name as debtor_name, b.username as debtor_username
            FROM debts d
            JOIN users c ON d.creditor_id = c.user_id
            JOIN users b ON d.debtor_id = b.user_id
            WHERE (d.creditor_id = ? OR d.debtor_id = ?)
            AND d.status IN ('active', 'pending')
            ORDER BY d.created_at DESC
        ''', (user_id, user_id))
        
        debts = cursor.fetchall()
        conn.close()
        
        return [dict(debt) for debt in debts]
    
    def get_debts_i_owe(self, user_id):
        """Get debts where user is the debtor"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   c.first_name as creditor_name, c.username as creditor_username
            FROM debts d
            JOIN users c ON d.creditor_id = c.user_id
            WHERE d.debtor_id = ? AND d.status = 'active'
            ORDER BY d.created_at DESC
        ''', (user_id,))
        
        debts = cursor.fetchall()
        conn.close()
        
        return [dict(debt) for debt in debts]
    
    def get_debts_owed_to_me(self, user_id):
        """Get debts where user is the creditor"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   b.first_name as debtor_name, b.username as debtor_username
            FROM debts d
            JOIN users b ON d.debtor_id = b.user_id
            WHERE d.creditor_id = ? AND d.status = 'active'
            ORDER BY d.created_at DESC
        ''', (user_id,))
        
        debts = cursor.fetchall()
        conn.close()
        
        return [dict(debt) for debt in debts]
    
    def add_payment(self, debt_id, payer_id, amount):
        """Add a partial payment to a debt"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO payments (debt_id, payer_id, amount, confirmed)
            VALUES (?, ?, ?, FALSE)
        ''', (debt_id, payer_id, amount))
        
        payment_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return payment_id
    
    def confirm_payment(self, payment_id):
        """Confirm a payment"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE payments SET confirmed = TRUE WHERE id = ?', (payment_id,))
        
        # Get payment info
        cursor.execute('SELECT * FROM payments WHERE id = ?', (payment_id,))
        payment = cursor.fetchone()
        
        if payment:
            # Check if debt is fully paid
            cursor.execute('''
                SELECT d.amount, COALESCE(SUM(p.amount), 0) as total_paid
                FROM debts d
                LEFT JOIN payments p ON d.id = p.debt_id AND p.confirmed = TRUE
                WHERE d.id = ?
                GROUP BY d.id
            ''', (payment['debt_id'],))
            
            result = cursor.fetchone()
            if result and result['total_paid'] >= result['amount']:
                cursor.execute('UPDATE debts SET status = "paid" WHERE id = ?', (payment['debt_id'],))
        
        conn.commit()
        conn.close()
        return True
    
    def get_debt_balance(self, debt_id):
        """Get remaining balance for a debt"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.amount, COALESCE(SUM(p.amount), 0) as total_paid
            FROM debts d
            LEFT JOIN payments p ON d.id = p.debt_id AND p.confirmed = TRUE
            WHERE d.id = ?
            GROUP BY d.id
        ''', (debt_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result['amount'] - result['total_paid']
        return 0
    
    def cancel_debt(self, debt_id, user_id):
        """Cancel a debt (only creator can cancel)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT creator_id FROM debts WHERE id = ?', (debt_id,))
        debt = cursor.fetchone()
        
        if debt and debt['creator_id'] == user_id:
            cursor.execute('UPDATE debts SET status = "cancelled" WHERE id = ?', (debt_id,))
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False
    
    def create_notification(self, user_id, debt_id, message, notif_type):
        """Create a notification for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO notifications (user_id, debt_id, message, type)
            VALUES (?, ?, ?, ?)
        ''', (user_id, debt_id, message, notif_type))
        
        conn.commit()
        conn.close()
    
    def get_unread_notifications(self, user_id):
        """Get unread notifications for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM notifications
            WHERE user_id = ? AND read = FALSE
            ORDER BY created_at DESC
        ''', (user_id,))
        
        notifications = cursor.fetchall()
        conn.close()
        
        return [dict(notif) for notif in notifications]
    
    def mark_notification_read(self, notification_id):
        """Mark notification as read"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE notifications SET read = TRUE WHERE id = ?', (notification_id,))
        conn.commit()
        conn.close()