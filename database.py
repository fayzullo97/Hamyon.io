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
                creditor_id INTEGER,
                debtor_id INTEGER,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'so''m',
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_by_creditor BOOLEAN DEFAULT FALSE,
                confirmed_by_debtor BOOLEAN DEFAULT FALSE,
                creditor_username TEXT,
                debtor_username TEXT,
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
        # User circles/categories table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_circles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                circle_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, circle_name)
            )
        ''')
        
        # Circle members table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS circle_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                circle_id INTEGER NOT NULL,
                member_name TEXT NOT NULL,
                member_user_id INTEGER,
                member_username TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (circle_id) REFERENCES user_circles(id),
                FOREIGN KEY (member_user_id) REFERENCES users(user_id)
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
    
    def link_pending_debts(self, username, user_id):
        """Link pending debts to newly registered user based on username"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Link as creditor
        cursor.execute('''
            UPDATE debts
            SET creditor_id = ?, creditor_username = NULL
            WHERE creditor_username = ? AND creditor_id IS NULL
        ''', (user_id, username))
        
        # Link as debtor
        cursor.execute('''
            UPDATE debts
            SET debtor_id = ?, debtor_username = NULL
            WHERE debtor_username = ? AND debtor_id IS NULL
        ''', (user_id, username))
        
        conn.commit()
        conn.close()
    
    def create_debt(self, creator_id, creditor_id, debtor_id, amount, currency, reason, creditor_username=None, debtor_username=None):
        """Create a new debt record, allowing null IDs with usernames"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO debts (creator_id, creditor_id, debtor_id, amount, currency, reason, status, creditor_username, debtor_username)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        ''', (creator_id, creditor_id, debtor_id, amount, currency, reason, creditor_username, debtor_username))
        
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
        """Get debt by ID, with fallback to usernames"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   c.first_name as creditor_first_name, c.username as creditor_db_username,
                   b.first_name as debtor_first_name, b.username as debtor_db_username,
                   cr.first_name as creator_name
            FROM debts d
            LEFT JOIN users c ON d.creditor_id = c.user_id
            LEFT JOIN users b ON d.debtor_id = b.user_id
            JOIN users cr ON d.creator_id = cr.user_id
            WHERE d.id = ?
        ''', (debt_id,))
        
        debt = cursor.fetchone()
        conn.close()
        
        if debt:
            debt_dict = dict(debt)
            debt_dict['creditor_name'] = debt_dict['creditor_first_name'] or debt_dict['creditor_username']
            debt_dict['debtor_name'] = debt_dict['debtor_first_name'] or debt_dict['debtor_username']
            debt_dict['creditor_username'] = debt_dict['creditor_db_username'] or debt_dict['creditor_username']
            debt_dict['debtor_username'] = debt_dict['debtor_db_username'] or debt_dict['debtor_username']
            return debt_dict
        return None
    
    def get_user_debts(self, user_id):
        """Get all debts for a user, with fallback to usernames"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   c.first_name as creditor_first_name, c.username as creditor_db_username,
                   b.first_name as debtor_first_name, b.username as debtor_db_username
            FROM debts d
            LEFT JOIN users c ON d.creditor_id = c.user_id
            LEFT JOIN users b ON d.debtor_id = b.user_id
            WHERE (d.creditor_id = ? OR d.debtor_id = ?)
            AND d.status IN ('active', 'pending')
            ORDER BY d.created_at DESC
        ''', (user_id, user_id))
        
        debts = cursor.fetchall()
        conn.close()
        
        debt_list = []
        for debt in debts:
            debt_dict = dict(debt)
            debt_dict['creditor_name'] = debt_dict['creditor_first_name'] or debt_dict['creditor_username']
            debt_dict['debtor_name'] = debt_dict['debtor_first_name'] or debt_dict['debtor_username']
            debt_list.append(debt_dict)
        return debt_list
    
    def get_debts_i_owe(self, user_id):
        """Get debts where user is the debtor, with fallback"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   c.first_name as creditor_first_name, c.username as creditor_db_username
            FROM debts d
            LEFT JOIN users c ON d.creditor_id = c.user_id
            WHERE d.debtor_id = ? AND d.status = 'active'
            ORDER BY d.created_at DESC
        ''', (user_id,))
        
        debts = cursor.fetchall()
        conn.close()
        
        debt_list = []
        for debt in debts:
            debt_dict = dict(debt)
            debt_dict['creditor_name'] = debt_dict['creditor_first_name'] or debt_dict['creditor_username']
            debt_list.append(debt_dict)
        return debt_list
    
    def get_debts_owed_to_me(self, user_id):
        """Get debts where user is the creditor, with fallback"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   b.first_name as debtor_first_name, b.username as debtor_db_username
            FROM debts d
            LEFT JOIN users b ON d.debtor_id = b.user_id
            WHERE d.creditor_id = ? AND d.status = 'active'
            ORDER BY d.created_at DESC
        ''', (user_id,))
        
        debts = cursor.fetchall()
        conn.close()
        
        debt_list = []
        for debt in debts:
            debt_dict = dict(debt)
            # Fallback to username if no first_name
            debt_dict['debtor_name'] = (
                debt_dict['debtor_first_name'] or 
                debt_dict.get('debtor_username', 'Noma\'lum') or 
                'Noma\'lum'
            )
            debt_list.append(debt_dict)
        return debt_list
    
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
    
    def create_circle(self, user_id, circle_name):
        """Create a user circle/category"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR IGNORE INTO user_circles (user_id, circle_name)
            VALUES (?, ?)
        ''', (user_id, circle_name))
        
        circle_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return circle_id
    
    def add_member_to_circle(self, circle_id, member_name, member_user_id=None, member_username=None):
        """Add member to circle"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO circle_members (circle_id, member_name, member_user_id, member_username)
            VALUES (?, ?, ?, ?)
        ''', (circle_id, member_name, member_user_id, member_username))
        
        conn.commit()
        conn.close()
    
    def get_user_circles(self, user_id):
        """Get all circles for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM user_circles
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (user_id,))
        
        circles = cursor.fetchall()
        conn.close()
        return [dict(circle) for circle in circles]
    
    def get_circle_members(self, circle_id):
        """Get all members of a circle"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT cm.*, u.username as db_username
            FROM circle_members cm
            LEFT JOIN users u ON cm.member_user_id = u.user_id
            WHERE cm.circle_id = ?
        ''', (circle_id,))
        
        members = cursor.fetchall()
        conn.close()
        return [dict(member) for member in members]
    
    def find_circle_by_members(self, user_id, member_names):
        """Find circle that matches these members"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get all circles for user
        cursor.execute('SELECT id FROM user_circles WHERE user_id = ?', (user_id,))
        circles = cursor.fetchall()
        
        for circle in circles:
            circle_id = circle['id']
            cursor.execute('''
                SELECT member_name FROM circle_members WHERE circle_id = ?
            ''', (circle_id,))
            
            circle_members = [m['member_name'] for m in cursor.fetchall()]
            
            # Check if members match (at least 50% overlap)
            overlap = len(set(member_names) & set(circle_members))
            if overlap >= len(member_names) * 0.5:
                conn.close()
                return circle_id
        
        conn.close()
        return None