import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import openai
from datetime import datetime
import json
import re
from database import Database

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database
db = Database()

# OpenAI client
openai.api_key = os.getenv('OPENAI_API_KEY')

class DebtBot:
    def __init__(self):
        self.db = db
        self.pending_debts = {}
        self.user_context = {}
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        self.db.create_user(user.id, user.username, user.first_name, user.last_name)
        
        keyboard = [
            [KeyboardButton("📊 Mening qarzlarim"), KeyboardButton("💰 Men qarzdorman")],
            [KeyboardButton("💵 Menga qarzlar"), KeyboardButton("📜 Tarix")],
            [KeyboardButton("ℹ️ Yordam"), KeyboardButton("📊 Statistika")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_message = (
            f"👋 Salom, {user.first_name}!\n\n"
            "Men Telegram orqali qarzlar va umumiy xarajatlarni boshqarish botiman.\n\n"
            "🎤 *Ovozli xabar yuboring* va men:\n"
            "• Qarz yoki xarajatni qayd qilaman\n"
            "• Ishtirokchilarni bog'layman\n"
            "• Tasdiqlash so'rayman\n"
            "• Barcha ishtirokchilarga xabar beraman\n\n"
            "📝 *Misollar:*\n"
            "• \"Alisher menga 50 ming so'm qarz berdi lunch uchun\"\n"
            "• \"Men Dilnozaga 100 ming so'm qarz berdim\"\n"
            "• \"Bobur menga 75 ming so'm to'lashi kerak taxi uchun\"\n\n"
            "🔍 *Agar username bilmasangiz:*\n"
            "Kontaktni ulashish orqali foydalanuvchini topishingiz mumkin.\n\n"
            "Ovozli xabar yuboring yoki quyidagi tugmalardan foydalaning!"
        )
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help message"""
        help_text = (
            "📖 *Yordam*\n\n"
            "*Qarz yaratish:*\n"
            "🎤 Ovozli xabar yuboring:\n"
            "• \"[Ism] menga [summa] qarz berdi [sabab uchun]\"\n"
            "• \"Men [ism]ga [summa] qarz berdim [sabab uchun]\"\n\n"
            "*Misollar:*\n"
            "• \"Alisher menga 50 ming so'm qarz berdi lunch uchun\"\n"
            "• \"Men Dilnozaga 100000 so'm berdim kitob uchun\"\n\n"
            "*Tugmalar:*\n"
            "📊 Mening qarzlarim - Barcha qarzlarni ko'rish\n"
            "💰 Men qarzdorman - Men to'lashim kerak bo'lgan qarzlar\n"
            "💵 Menga qarzlar - Menga to'lashlari kerak bo'lgan qarzlar\n"
            "📜 Tarix - To'liq tarix\n"
            "📊 Statistika - Umumiy statistika\n\n"
            "*Qisman to'lov:*\n"
            "Qarz ro'yxatida qarzni tanlang va to'lov qiling.\n\n"
            "*Bekor qilish:*\n"
            "Faqat qarz yaratuvchi bekor qilishi mumkin."
        )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice messages"""
        user = update.effective_user
        
        processing_msg = await update.message.reply_text("🎤 Ovozli xabaringizni tinglayapman...")
        
        try:
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)
            
            voice_path = f"voice_{user.id}_{datetime.now().timestamp()}.ogg"
            await file.download_to_drive(voice_path)
            
            with open(voice_path, 'rb') as audio_file:
                transcript = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="uz"
                )
            
            transcribed_text = transcript.text
            
            if os.path.exists(voice_path):
                os.remove(voice_path)
            
            await processing_msg.edit_text(
                f"📝 Matn: _{transcribed_text}_\n\n⏳ Tahlil qilyapman...", 
                parse_mode='Markdown'
            )
            
            debt_info = await self.parse_debt_info(transcribed_text, user)
            
            if debt_info.get('error'):
                await processing_msg.edit_text(
                    f"❌ {debt_info['error']}\n\n"
                    "Iltimos, qaytadan urinib ko'ring. Misol:\n"
                    "\"Alisher menga 50 ming so'm qarz berdi lunch uchun\""
                )
                return
            
            missing = self.check_missing_info(debt_info)
            if missing:
                await self.request_missing_info(update, context, debt_info, missing, processing_msg)
                return
            
            await self.create_debt_confirmation(update, context, debt_info, processing_msg)
            
        except Exception as e:
            logger.error(f"Error processing voice: {e}")
            await processing_msg.edit_text(
                "❌ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.\n"
                f"Xato: {str(e)[:100]}"
            )
    
    async def parse_debt_info(self, text: str, user):
        """Use GPT to parse debt information from text"""
        try:
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": """Sen qarz va xarajatlarni tahlil qiluvchi yordamchisan. 
                    Foydalanuvchi matnidan quyidagi ma'lumotlarni ajratib ol va JSON formatida qaytaring.
                    
                    Kerakli ma'lumotlar:
                    - amount: pul miqdori (faqat raqam, masalan: 50000)
                    - currency: har doim "so'm"
                    - creditor_name: qarz beruvchi ism (kim qarz berdi yoki kim to'ladi)
                    - debtor_name: qarz oluvchi ism (kim qarz oldi yoki kim to'lashi kerak)  
                    - reason: sabab (nima uchun)
                    - direction: "i_owe" (men qarzdorman) yoki "owe_me" (menga qarz)
                    
                    Qoidalar:
                    - "menga qarz berdi" = direction: "owe_me", creditor_name = boshqa odam
                    - "men qarz berdim" = direction: "i_owe", debtor_name = boshqa odam
                    - "to'lashi kerak" = direction: "owe_me"
                    - Miqdorni raqamga aylantiring (50 ming = 50000, yuz ming = 100000)
                    - Agar ma'lumot topilmasa, null qo'ying
                    
                    Faqat JSON qaytaring, boshqa hech narsa yo'q."""},
                    {"role": "user", "content": text}
                ],
                temperature=0.3
            )
            
            result = json.loads(response.choices[0].message.content)
            result['original_text'] = text
            logger.info(f"Parsed debt info: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error parsing debt info: {e}")
            return {'error': 'Matnni tushunib bo\'lmadi. Iltimos, aniqroq aytib bering.'}
    
    def check_missing_info(self, debt_info):
        """Check what information is missing"""
        missing = []
        if not debt_info.get('amount'):
            missing.append('amount')
        
        direction = debt_info.get('direction')
        if direction == 'owe_me' and not debt_info.get('creditor_name'):
            missing.append('creditor_name')
        elif direction == 'i_owe' and not debt_info.get('debtor_name'):
            missing.append('debtor_name')
        elif not direction:
            missing.append('direction')
            
        return missing
    
    async def request_missing_info(self, update, context, debt_info, missing, processing_msg):
        """Request missing information from user"""
        questions = {
            'amount': "💰 Qancha pul? (masalan: 50000 yoki 50 ming)",
            'creditor_name': "👤 Kim qarz berdi? (ism yoki @username)",
            'debtor_name': "👤 Kimga qarz berdingiz? (ism yoki @username)",
            'direction': "❓ Kim kimga qarz berdi? Iltimos aniqroq ayting.",
            'reason': "📝 Nima uchun? (masalan: lunch, taxi, kitob)"
        }
        
        question = questions.get(missing[0], "Ma'lumot to'liq emas")
        
        self.user_context[update.effective_user.id] = {
            'debt_info': debt_info,
            'missing': missing,
            'step': 0,
            'message_id': processing_msg.message_id
        }
        
        await processing_msg.edit_text(f"❓ {question}")
    
    async def create_debt_confirmation(self, update, context, debt_info, processing_msg):
        """Create debt and send confirmation request"""
        user = update.effective_user
        
        direction = debt_info.get('direction')
        
        if direction == 'owe_me':
            creditor_id = user.id
            creditor_name = user.first_name
            debtor_name = debt_info.get('creditor_name') or debt_info.get('debtor_name')
        else:
            debtor_id = user.id
            debtor_name = user.first_name
            creditor_name = debt_info.get('creditor_name') or debt_info.get('debtor_name')
        
        other_user = None
        if debtor_name and debtor_name.startswith('@'):
            other_user = self.db.find_user_by_username(debtor_name)
        elif creditor_name and creditor_name.startswith('@'):
            other_user = self.db.find_user_by_username(creditor_name)
        
        debt_id = f"pending_{user.id}_{int(datetime.now().timestamp())}"
        self.pending_debts[debt_id] = {
            'creator_id': user.id,
            'creditor_id': creditor_id if direction == 'owe_me' else (other_user['user_id'] if other_user else None),
            'debtor_id': debtor_id if direction == 'i_owe' else (other_user['user_id'] if other_user else None),
            'creditor_name': creditor_name,
            'debtor_name': debtor_name,
            'amount': debt_info['amount'],
            'currency': debt_info.get('currency', "so'm"),
            'reason': debt_info.get('reason', 'Sababsiz'),
            'direction': direction,
            'other_user': other_user
        }
        
        newline = '\n'
        confirmation_text = (
            f"✅ *Tasdiqlash kerak:*{newline}{newline}"
            f"💰 Summa: {debt_info['amount']:,} {debt_info.get('currency', 'so\'m')}{newline}"
            f"📝 Sabab: {debt_info.get('reason', 'Sababsiz')}{newline}"
            f"👤 Qarz beruvchi: {creditor_name}{newline}"
            f"👤 Qarz oluvchi: {debtor_name}{newline}{newline}"
        )
        
        if not other_user:
            confirmation_text += (
                f"⚠️ *Diqqat:* Foydalanuvchi topilmadi.{newline}"
                f"Agar username bilsangiz, @username formatida kiriting.{newline}"
                f"Yoki kontaktni ulashing.{newline}{newline}"
            )
        
        confirmation_text += "Bu ma'lumot to'g'rimi?"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{debt_id}"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_{debt_id}")
            ]
        ]
        
        if not other_user:
            keyboard.append([
                InlineKeyboardButton("🔍 Username kiritish", callback_data=f"adduser_{debt_id}")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await processing_msg.edit_text(confirmation_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith('confirm_'):
            await self.confirm_debt_callback(query, data)
        elif data.startswith('cancel_'):
            debt_id = data.replace('cancel_', '')
            if debt_id in self.pending_debts:
                del self.pending_debts[debt_id]
            await query.edit_message_text("❌ Qarz bekor qilindi.")
        elif data.startswith('accept_debt_'):
            await self.accept_debt_callback(query, data)
        elif data.startswith('dispute_debt_'):
            await self.dispute_debt_callback(query, data)
        elif data.startswith('pay_'):
            await self.initiate_payment(query, data)
        elif data.startswith('cancel_debt_'):
            await self.cancel_debt_callback(query, data)
        elif data.startswith('remind_'):
            await self.send_reminder_callback(query, data)
    
    async def confirm_debt_callback(self, query, data):
        """Handle debt confirmation from creator"""
        debt_id = data.replace('confirm_', '')
        
        if debt_id not in self.pending_debts:
            await query.edit_message_text("❌ Qarz topilmadi yoki muddati o'tgan.")
            return
        
        debt_data = self.pending_debts[debt_id]
        
        if not debt_data.get('creditor_id') or not debt_data.get('debtor_id'):
            await query.edit_message_text(
                "❌ Ikkinchi foydalanuvchi topilmadi.\n"
                "Iltimos, to'g'ri @username kiriting yoki kontakt ulashing."
            )
            return
        
        created_debt_id = self.db.create_debt(
            creator_id=debt_data['creator_id'],
            creditor_id=debt_data['creditor_id'],
            debtor_id=debt_data['debtor_id'],
            amount=debt_data['amount'],
            currency=debt_data['currency'],
            reason=debt_data['reason']
        )
        
        if debt_data['creator_id'] == debt_data['creditor_id']:
            self.db.confirm_debt(created_debt_id, debt_data['creator_id'])
        elif debt_data['creator_id'] == debt_data['debtor_id']:
            self.db.confirm_debt(created_debt_id, debt_data['creator_id'])
        
        other_user_id = debt_data['debtor_id'] if debt_data['creator_id'] == debt_data['creditor_id'] else debt_data['creditor_id']
        
        newline = '\n'
        notification_text = (
            f"🔔 *Yangi qarz xabarnomasi*{newline}{newline}"
            f"💰 Summa: {debt_data['amount']:,} {debt_data['currency']}{newline}"
            f"📝 Sabab: {debt_data['reason']}{newline}"
            f"👤 Yaratuvchi: {debt_data.get('creditor_name') if debt_data['creator_id'] == debt_data['creditor_id'] else debt_data.get('debtor_name')}{newline}{newline}"
        )
        
        if debt_data['creator_id'] == debt_data['creditor_id']:
            notification_text += "Sizga qarz sifatida qayd qilindi."
        else:
            notification_text += "Sizdan qarz sifatida qayd qilindi."
        
        notification_text += f"{newline}{newline}Iltimos, tasdiqlang:"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"accept_debt_{created_debt_id}"),
                InlineKeyboardButton("❌ E'tiroz", callback_data=f"dispute_debt_{created_debt_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.get_bot().send_message(
                chat_id=other_user_id,
                text=notification_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            await query.edit_message_text(
                f"✅ *Qarz yaratildi!*{newline}{newline}"
                f"💰 Summa: {debt_data['amount']:,} {debt_data['currency']}{newline}"
                f"📝 Sabab: {debt_data['reason']}{newline}{newline}"
                f"Ikkinchi tomonga xabarnoma yuborildi.{newline}"
                "Ular tasdiqlaganidan keyin qarz faollashadi.",
                parse_mode='Markdown'
            )
            
            self.db.create_notification(
                other_user_id, 
                created_debt_id, 
                notification_text, 
                'debt_created'
            )
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            await query.edit_message_text(
                "⚠️ Qarz yaratildi, lekin xabarnoma yuborilmadi.\n"
                "Ikkinchi foydalanuvchi botni ishga tushirmagan bo'lishi mumkin."
            )
        
        del self.pending_debts[debt_id]
    
    async def accept_debt_callback(self, query, data):
        """Handle debt acceptance"""
        debt_id = int(data.replace('accept_debt_', ''))
        user_id = query.from_user.id
        
        if self.db.confirm_debt(debt_id, user_id):
            debt = self.db.get_debt(debt_id)
            
            newline = '\n'
            if debt and debt['status'] == 'active':
                await query.edit_message_text(
                    f"✅ *Qarz tasdiqlandi va faollashdi!*{newline}{newline}"
                    f"💰 Summa: {debt['amount']:,} {debt['currency']}{newline}"
                    f"📝 Sabab: {debt['reason']}{newline}{newline}"
                    "Qarz endi faol va to'lanishi mumkin.",
                    parse_mode='Markdown'
                )
                
                creator_id = debt['creator_id']
                try:
                    await query.get_bot().send_message(
                        chat_id=creator_id,
                        text=f"✅ Sizning {debt['amount']:,} {debt['currency']} qarzingiz tasdiqlandi va faollashdi!",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                await query.edit_message_text(
                    "✅ Sizning tasdiqingiz qayd qilindi.\n"
                    "Ikkinchi tomon ham tasdiqlashi kerak."
                )
        else:
            await query.edit_message_text("❌ Xatolik yuz berdi.")
    
    async def dispute_debt_callback(self, query, data):
        """Handle debt dispute"""
        debt_id = int(data.replace('dispute_debt_', ''))
        debt = self.db.get_debt(debt_id)
        
        if debt:
            self.db.cancel_debt(debt_id, debt['creator_id'])
            
            await query.edit_message_text(
                "❌ Qarzga e'tiroz bildirdingiz.\n"
                "Qarz bekor qilindi."
            )
            
            try:
                await query.get_bot().send_message(
                    chat_id=debt['creator_id'],
                    text=f"❌ Sizning {debt['amount']:,} {debt['currency']} qarzingizga e'tiroz bildirildi va bekor qilindi."
                )
            except:
                pass
    
    async def show_my_debts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all user's debts"""
        user_id = update.effective_user.id
        
        debts = self.db.get_user_debts(user_id)
        
        if not debts:
            await update.message.reply_text(
                "📊 Sizda hozircha faol qarzlar yo'q.\n\n"
                "Qarz yaratish uchun ovozli xabar yuboring!"
            )
            return
        
        nl = '\n'
        message = f"📊 *Mening qarzlarim:*{nl}{nl}"
        
        total_owe = 0
        total_owed = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            
            if debt['debtor_id'] == user_id:
                total_owe += balance
                status_icon = "🔴" if debt['status'] == 'active' else "🟡"
                message += f"{status_icon} *#{debt['id']}* Men {debt['creditor_name']}ga qarzdorman{nl}"
                message += f"   💰 {balance:,} so'm{nl}"
                message += f"   📝 {debt['reason']}{nl}"
                message += f"   📅 {debt['created_at'][:10]}{nl}{nl}"
            else:
                total_owed += balance
                status_icon = "🟢" if debt['status'] == 'active' else "🟡"
                message += f"{status_icon} *#{debt['id']}* {debt['debtor_name']} menga qarz{nl}"
                message += f"   💰 {balance:,} so'm{nl}"
                message += f"   📝 {debt['reason']}{nl}"
                message += f"   📅 {debt['created_at'][:10]}{nl}{nl}"
        
        message += f"━━━━━━━━━━━━━━━━{nl}"
        message += f"💰 *Jami:*{nl}"
        message += f"❌ Men to'lashim kerak: {total_owe:,} so'm{nl}"
        message += f"✅ Menga to'lashlari kerak: {total_owed:,} so'm{nl}"
        message += f"📊 Balans: {(total_owed - total_owe):+,} so'm"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def show_i_owe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show debts where user is the debtor"""
        user_id = update.effective_user.id
        debts = self.db.get_debts_i_owe(user_id)
        
        if not debts:
            await update.message.reply_text("💰 Sizda to'lash uchun qarzlar yo'q! 🎉")
            return
        
        nl = '\n'
        message = f"💰 *Men qarzdorman:*{nl}{nl}"
        total = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            total += balance
            message += f"🔴 *#{debt['id']}* {debt['creditor_name']}ga{nl}"
            message += f"   💵 {balance:,} so'm{nl}"
            message += f"   📝 {debt['reason']}{nl}"
            message += f"   📅 {debt['created_at'][:10]}{nl}{nl}"
        
        message += f"━━━━━━━━━━━━━━━━{nl}"
        message += f"💰 Jami: {total:,} so'm"
        
        keyboard = []
        for debt in debts[:5]:
            balance = self.db.get_debt_balance(debt['id'])
            if balance > 0:
                keyboard.append([
                    InlineKeyboardButton(
                        f"💳 To'lash #{debt['id']} ({balance:,} so'm)", 
                        callback_data=f"pay_{debt['id']}"
                    )
                ])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def show_owed_to_me(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show debts where user is the creditor"""
        user_id = update.effective_user.id
        debts = self.db.get_debts_owed_to_me(user_id)
        
        if not debts:
            await update.message.reply_text("💵 Sizga hech kim qarz emas.")
            return
        
        nl = '\n'
        message = f"💵 *Menga qarzlar:*{nl}{nl}"
        total = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            total += balance
            message += f"🟢 *#{debt['id']}* {debt['debtor_name']}dan{nl}"
            message += f"   💵 {balance:,} so'm{nl}"
            message += f"   📝 {debt['reason']}{nl}"
            message += f"   📅 {debt['created_at'][:10]}{nl}{nl}"
        
        message += f"━━━━━━━━━━━━━━━━{nl}"
        message += f"💰 Jami: {total:,} so'm"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user statistics"""
        user_id = update.effective_user.id
        
        all_debts = self.db.get_user_debts(user_id)
        
        total_owe = 0
        total_owed = 0
        active_count = 0
        pending_count = 0
        paid_count = 0
        
        for debt in all_debts:
            balance = self.db.get_debt_balance(debt['id'])
            
            if debt['status'] == 'active':
                active_count += 1
                if debt['debtor_id'] == user_id:
                    total_owe += balance
                else:
                    total_owed += balance
            elif debt['status'] == 'pending':
                pending_count += 1
            elif debt['status'] == 'paid':
                paid_count += 1
        
        nl = '\n'
        stats_message = (
            f"📊 *Statistika:*{nl}{nl}"
            f"📈 Faol qarzlar: {active_count}{nl}"
            f"🕐 Kutilmoqda: {pending_count}{nl}"
            f"✅ To'langan: {paid_count}{nl}{nl}"
            f"━━━━━━━━━━━━━━━━{nl}"
            f"💰 *Moliyaviy holat:*{nl}"
            f"❌ Men qarzdorman: {total_owe:,} so'm{nl}"
            f"✅ Menga qarz: {total_owed:,} so'm{nl}"
            f"📊 Balans: {(total_owed - total_owe):+,} so'm"
        )
        
        await update.message.reply_text(stats_message, parse_mode='Markdown')
    
    async def show_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show complete history of all debts"""
        user_id = update.effective_user.id
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, 
                   c.first_name as creditor_name,
                   b.first_name as debtor_name
            FROM debts d
            JOIN users c ON d.creditor_id = c.user_id
            JOIN users b ON d.debtor_id = b.user_id
            WHERE d.creditor_id = ? OR d.debtor_id = ?
            ORDER BY d.created_at DESC
            LIMIT 20
        ''', (user_id, user_id))
        
        debts = cursor.fetchall()
        conn.close()
        
        if not debts:
            await update.message.reply_text("📜 Tarix bo'sh.")
            return
        
        nl = '\n'
        message = f"📜 *Tarix (oxirgi 20):*{nl}{nl}"
        
        for debt in debts:
            debt_dict = dict(debt)
            status_emoji = {
                'pending': '🟡',
                'active': '🔵',
                'paid': '✅',
                'cancelled': '❌'
            }
            
            emoji = status_emoji.get(debt_dict['status'], '⚪')
            message += f"{emoji} *#{debt_dict['id']}* "
            
            if debt_dict['debtor_id'] == user_id:
                message += f"{debt_dict['creditor_name']}ga qarzdor{nl}"
            else:
                message += f"{debt_dict['debtor_name']}dan qarz{nl}"
            
            message += f"   💰 {debt_dict['amount']:,} so'm{nl}"
            message += f"   📝 {debt_dict['reason']}{nl}"
            message += f"   📅 {debt_dict['created_at'][:10]}{nl}"
            message += f"   Status: {debt_dict['status']}{nl}{nl}"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def send_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send reminder to debtor"""
        user_id = update.effective_user.id
        debts = self.db.get_debts_owed_to_me(user_id)
        
        if not debts:
            await update.message.reply_text("💵 Sizga hech kim qarz emas.")
            return
        
        keyboard = []
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            if balance > 0:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🔔 #{debt['id']} - {debt['debtor_name']} ({balance:,} so'm)",
                        callback_data=f"remind_{debt['id']}"
                    )
                ])
        
        if keyboard:
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "🔔 *Eslatma yuborish*\n\nQaysi qarz uchun eslatma yubormoqchisiz?",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text("Barcha qarzlar to'langan!")
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle shared contact"""
        contact = update.message.contact
        user_id = update.effective_user.id
        
        self.db.create_user(
            contact.user_id,
            None,
            contact.first_name,
            contact.last_name
        )
        
        if user_id in self.user_context and 'debt_info' in self.user_context[user_id]:
            debt_ctx = self.user_context[user_id]
            debt_info = debt_ctx['debt_info']
            
            if debt_info.get('direction') == 'owe_me':
                debt_info['creditor_name'] = contact.first_name
            else:
                debt_info['debtor_name'] = contact.first_name
            
            debt_ctx['contact_user_id'] = contact.user_id
            
            await update.message.reply_text(
                f"✅ Kontakt qabul qilindi: {contact.first_name}\n\n"
                "Iltimos, davom etish uchun qolgan ma'lumotlarni kiriting."
            )
        else:
            await update.message.reply_text(
                f"✅ Kontakt saqlandi: {contact.first_name}\n\n"
                "Endi ovozli xabar yuboring va bu foydalanuvchi bilan qarz yarating."
            )
    
    async def initiate_payment(self, query, data):
        """Initiate partial payment"""
        debt_id = int(data.replace('pay_', ''))
        debt = self.db.get_debt(debt_id)
        
        if not debt:
            await query.edit_message_text("❌ Qarz topilmadi.")
            return
        
        balance = self.db.get_debt_balance(debt_id)
        
        if balance <= 0:
            await query.edit_message_text("✅ Bu qarz allaqachon to'langan!")
            return
        
        self.user_context[query.from_user.id] = {
            'action': 'payment',
            'debt_id': debt_id,
            'balance': balance
        }
        
        nl = '\n'
        await query.message.reply_text(
            f"💳 *To'lov:*{nl}{nl}"
            f"Qarz: #{debt_id}{nl}"
            f"Qolgan summa: {balance:,} so'm{nl}{nl}"
            "Qancha to'lamoqchisiz? (raqam kiriting)",
            parse_mode='Markdown'
        )
    
    async def cancel_debt_callback(self, query, data):
        """Cancel debt (only creator can cancel)"""
        debt_id = int(data.replace('cancel_debt_', ''))
        user_id = query.from_user.id
        
        if self.db.cancel_debt(debt_id, user_id):
            await query.edit_message_text("✅ Qarz bekor qilindi.")
        else:
            await query.edit_message_text("❌ Faqat qarz yaratuvchi bekor qilishi mumkin.")
    
    async def send_reminder_callback(self, query, data):
        """Send reminder to debtor"""
        debt_id = int(data.replace('remind_', ''))
        debt = self.db.get_debt(debt_id)
        
        if not debt or debt['creditor_id'] != query.from_user.id:
            await query.edit_message_text("❌ Xatolik yuz berdi.")
            return
        
        balance = self.db.get_debt_balance(debt_id)
        
        if balance <= 0:
            await query.edit_message_text("✅ Bu qarz allaqachon to'langan!")
            return
        
        nl = '\n'
        reminder_text = (
            f"🔔 *Eslatma*{nl}{nl}"
            f"Sizning {debt['creditor_name']}ga qarzingiz:{nl}"
            f"💰 Summa: {balance:,} so'm{nl}"
            f"📝 Sabab: {debt['reason']}{nl}"
            f"📅 Yaratilgan: {debt['created_at'][:10]}{nl}{nl}"
            "Iltimos, qarzni to'lashni unutmang!"
        )
        
        try:
            await query.get_bot().send_message(
                chat_id=debt['debtor_id'],
                text=reminder_text,
                parse_mode='Markdown'
            )
            
            await query.edit_message_text(
                f"✅ Eslatma yuborildi!{nl}{nl}"
                f"📨 {debt['debtor_name']}ga eslatma yuborildi."
            )
            
            self.db.create_notification(
                debt['debtor_id'],
                debt_id,
                "Qarz haqida eslatma olindi",
                'reminder'
            )
            
        except Exception as e:
            logger.error(f"Error sending reminder: {e}")
            await query.edit_message_text(
                "❌ Eslatma yuborilmadi.\n"
                "Foydalanuvchi botni bloklagan bo'lishi mumkin."
            )
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        text = update.message.text
        user_id = update.effective_user.id
        
        if text == "📊 Mening qarzlarim":
            await self.show_my_debts(update, context)
        elif text == "💰 Men qarzdorman":
            await self.show_i_owe(update, context)
        elif text == "💵 Menga qarzlar":
            await self.show_owed_to_me(update, context)
        elif text == "📜 Tarix":
            await self.show_history(update, context)
        elif text == "ℹ️ Yordam":
            await self.help_command(update, context)
        elif text == "📊 Statistika":
            await self.show_statistics(update, context)
        elif text.startswith("🔔") or text.lower().startswith("eslatma"):
            await self.send_reminder(update, context)
        else:
            if user_id in self.user_context:
                await self.handle_context_response(update, context)
            else:
                await update.message.reply_text(
                    "📱 Iltimos, qarz yoki xarajat haqida *ovozli xabar* yuboring.\n\n"
                    "Yoki kontakt ulashing va quyidagi tugmalardan foydalaning:",
                    parse_mode='Markdown'
                )
    
    async def handle_context_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user responses in context"""
        user_id = update.effective_user.id
        text = update.message.text
        user_ctx = self.user_context[user_id]
        
        if user_ctx.get('action') == 'payment':
            try:
                amount = float(text.replace(',', '').replace(' ', ''))
                debt_id = user_ctx['debt_id']
                balance = user_ctx['balance']
                
                if amount <= 0:
                    await update.message.reply_text("❌ Summa 0 dan katta bo'lishi kerak.")
                    return
                
                if amount > balance:
                    await update.message.reply_text(
                        f"❌ To'lov summasi qoldiqdan oshib ketdi.\n"
                        f"Qoldiq: {balance:,} so'm"
                    )
                    return
                
                payment_id = self.db.add_payment(debt_id, user_id, amount)
                debt = self.db.get_debt(debt_id)
                self.db.confirm_payment(payment_id)
                new_balance = self.db.get_debt_balance(debt_id)
                
                nl = '\n'
                if new_balance == 0:
                    await update.message.reply_text(
                        f"✅ *To'lov qabul qilindi!*{nl}{nl}"
                        f"💵 To'langan: {amount:,} so'm{nl}"
                        "🎉 Qarz to'liq to'landi!",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        f"✅ *To'lov qabul qilindi!*{nl}{nl}"
                        f"💵 To'langan: {amount:,} so'm{nl}"
                        f"📊 Qoldiq: {new_balance:,} so'm",
                        parse_mode='Markdown'
                    )
                
                try:
                    await context.bot.send_message(
                        chat_id=debt['creditor_id'],
                        text=f"💰 {debt['debtor_name']} {amount:,} so'm to'ladi!{nl}"
                             f"Qarz: #{debt_id}{nl}"
                             f"Qoldiq: {new_balance:,} so'm",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                
                del self.user_context[user_id]
                
            except ValueError:
                await update.message.reply_text("❌ Iltimos, to'g'ri raqam kiriting.")
        
        elif 'debt_info' in user_ctx:
            debt_info = user_ctx['debt_info']
            missing = user_ctx['missing']
            step = user_ctx['step']
            
            field = missing[step]
            if field == 'amount':
                try:
                    amount_str = text.replace(',', '').replace(' ', '').lower()
                    if 'ming' in amount_str:
                        amount_str = amount_str.replace('ming', '000')
                    amount = float(re.sub(r'[^\d.]', '', amount_str))
                    debt_info['amount'] = amount
                except:
                    await update.message.reply_text("❌ Summani tushunmadim. Iltimos, raqam kiriting (masalan: 50000)")
                    return
            elif field in ['creditor_name', 'debtor_name']:
                debt_info[field] = text
            elif field == 'reason':
                debt_info['reason'] = text
            
            if step + 1 < len(missing):
                user_ctx['step'] = step + 1
                next_field = missing[step + 1]
                questions = {
                    'amount': "💰 Qancha pul? (masalan: 50000)",
                    'creditor_name': "👤 Kim qarz berdi? (ism yoki @username)",
                    'debtor_name': "👤 Kimga qarz berdingiz? (ism yoki @username)",
                    'reason': "📝 Nima uchun?"
                }
                await update.message.reply_text(questions[next_field])
            else:
                del self.user_context[user_id]
                processing_msg = await update.message.reply_text("⏳ Qayd qilyapman...")
                await self.create_debt_confirmation(update, context, debt_info, processing_msg)

def main():
    """Start the bot"""
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    
    application = Application.builder().token(TOKEN).build()
    
    bot = DebtBot()
    
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(MessageHandler(filters.VOICE, bot.handle_voice))
    application.add_handler(MessageHandler(filters.CONTACT, bot.handle_contact))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    application.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()