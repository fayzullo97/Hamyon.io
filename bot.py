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
        self.pending_debts = {}  # Store pending debt confirmations
        self.user_context = {}   # Store user conversation context
        
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
        
        # Send processing message
        processing_msg = await update.message.reply_text("🎤 Ovozli xabaringizni tinglayapman...")
        
        try:
            # Get voice file
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)
            
            # Download voice file
            voice_path = f"voice_{user.id}_{datetime.now().timestamp()}.ogg"
            await file.download_to_drive(voice_path)
            
            # Transcribe using Whisper
            with open(voice_path, 'rb') as audio_file:
                transcript = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="uz"
                )
            
            transcribed_text = transcript.text
            
            # Clean up voice file
            if os.path.exists(voice_path):
                os.remove(voice_path)
            
            await processing_msg.edit_text(
                f"📝 Matn: _{transcribed_text}_\n\n⏳ Tahlil qilyapman...", 
                parse_mode='Markdown'
            )
            
            # Parse the debt information using GPT
            debt_info = await self.parse_debt_info(transcribed_text, user)
            
            if debt_info.get('error'):
                await processing_msg.edit_text(
                    f"❌ {debt_info['error']}\n\n"
                    "Iltimos, qaytadan urinib ko'ring. Misol:\n"
                    "\"Alisher menga 50 ming so'm qarz berdi lunch uchun\""
                )
                return
            
            # Request missing information
            missing = self.check_missing_info(debt_info)
            if missing:
                await self.request_missing_info(update, context, debt_info, missing, processing_msg)
                return
            
            # Create debt record and request confirmation
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
        
        # Store pending debt for follow-up
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
        
        # Determine creditor and debtor based on direction
        direction = debt_info.get('direction')
        
        if direction == 'owe_me':
            # Someone owes me
            creditor_id = user.id
            creditor_name = user.first_name
            debtor_name = debt_info.get('creditor_name') or debt_info.get('debtor_name')
        else:
            # I owe someone
            debtor_id = user.id
            debtor_name = user.first_name
            creditor_name = debt_info.get('creditor_name') or debt_info.get('debtor_name')
        
        # Try to find the other user
        other_user = None
        if debtor_name and debtor_name.startswith('@'):
            other_user = self.db.find_user_by_username(debtor_name)
        elif creditor_name and creditor_name.startswith('@'):
            other_user = self.db.find_user_by_username(creditor_name)
        
        # Store pending confirmation
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
        
        # Create confirmation message
        confirmation_text = (
            "✅ *Tasdiqlash kerak:*\n\n"
            f"💰 Summa: {debt_info['amount']:,} {debt_info.get('currency', 'so\'m')}\n"
            f"📝 Sabab: {debt_info.get('reason', 'Sababsiz')}\n"
            f"👤 Qarz beruvchi: {creditor_name}\n"
            f"👤 Qarz oluvchi: {debtor_name}\n\n"
        )
        
        if not other_user:
            confirmation_text += (
                "⚠️ *Diqqat:* Foydalanuvchi topilmadi.\n"
                "Agar username bilsangiz, @username formatida kiriting.\n"
                "Yoki kontaktni ulashing.\n\n"
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
        
        # Check if other user exists
        if not debt_data.get('creditor_id') or not debt_data.get('debtor_id'):
            await query.edit_message_text(
                "❌ Ikkinchi foydalanuvchi topilmadi.\n"
                "Iltimos, to'g'ri @username kiriting yoki kontakt ulashing."
            )
            return
        
        # Save to database
        created_debt_id = self.db.create_debt(
            creator_id=debt_data['creator_id'],
            creditor_id=debt_data['creditor_id'],
            debtor_id=debt_data['debtor_id'],
            amount=debt_data['amount'],
            currency=debt_data['currency'],
            reason=debt_data['reason']
        )
        
        # Auto-confirm creator's side
        if debt_data['creator_id'] == debt_data['creditor_id']:
            self.db.confirm_debt(created_debt_id, debt_data['creator_id'])
        elif debt_data['creator_id'] == debt_data['debtor_id']:
            self.db.confirm_debt(created_debt_id, debt_data['creator_id'])
        
        # Send notification to other party
        other_user_id = debt_data['debtor_id'] if debt_data['creator_id'] == debt_data['creditor_id'] else debt_data['creditor_id']
        
        notification_text = (
            "🔔 *Yangi qarz xabarnomasi*\n\n"
            f"💰 Summa: {debt_data['amount']:,} {debt_data['currency']}\n"
            f"📝 Sabab: {debt_data['reason']}\n"
            f"👤 Yaratuvchi: {debt_data.get('creditor_name') if debt_data['creator_id'] == debt_data['creditor_id'] else debt_data.get('debtor_name')}\n\n"
        )
        
        if debt_data['creator_id'] == debt_data['creditor_id']:
            notification_text += "Sizga qarz sifatida qayd qilindi."
        else:
            notification_text += "Sizdan qarz sifatida qayd qilindi."
        
        notification_text += "\n\nIltimos, tasdiqlang:"
        
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
                "✅ *Qarz yaratildi!*\n\n"
                f"💰 Summa: {debt_data['amount']:,} {debt_data['currency']}\n"
                f"📝 Sabab: {debt_data['reason']}\n\n"
                "Ikkinchi tomonga xabarnoma yuborildi.\n"
                "Ular tasdiqlaganidan keyin qarz faollashadi.",
                parse_mode='Markdown'
            )
            
            # Create notification in DB
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
        
        # Clean up pending debt
        del self.pending_debts[debt_id]
    
    async def accept_debt_callback(self, query, data):
        """Handle debt acceptance"""
        debt_id = int(data.replace('accept_debt_', ''))
        user_id = query.from_user.id
        
        # Confirm debt
        if self.db.confirm_debt(debt_id, user_id):
            debt = self.db.get_debt(debt_id)
            
            if debt and debt['status'] == 'active':
                await query.edit_message_text(
                    "✅ *Qarz tasdiqlandi va faollashdi!*\n\n"
                    f"💰 Summa: {debt['amount']:,} {debt['currency']}\n"
                    f"📝 Sabab: {debt['reason']}\n\n"
                    "Qarz endi faol va to'lanishi mumkin.",
                    parse_mode='Markdown'
                )
                
                # Notify creator
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
            # Cancel the debt
            self.db.cancel_debt(debt_id, debt['creator_id'])
            
            await query.edit_message_text(
                "❌ Qarzga e'tiroz bildirdingiz.\n"
                "Qarz bekor qilindi."
            )
            
            # Notify creator
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
        
        # Get debts from database
        debts = self.db.get_user_debts(user_id)
        
        if not debts:
            await update.message.reply_text(
                "📊 Sizda hozircha faol qarzlar yo'q.\n\n"
                "Qarz yaratish uchun ovozli xabar yuboring!"
            )
            return
        
        message = "📊 *Mening qarzlarim:*\n\n"
        
        total_owe = 0
        total_owed = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            
            if debt['debtor_id'] == user_id:
                total_owe += balance
                status_icon = "🔴" if debt['status'] == 'active' else "🟡"
                message += f"{status_icon} *#{debt['id']}* Men {debt['creditor_name']}ga qarzdorman\n"
                message += f"   💰 {balance:,} so'm\n"
                message += f"   📝 {debt['reason']}\n"
                message += f"   📅 {debt['created_at'][:10]}\n\n"
            else:
                total_owed += balance
                status_icon = "🟢" if debt['status'] == 'active' else "🟡"
                message += f"{status_icon} *#{debt['id']}* {debt['debtor_name']} menga qarz\n"
                message += f"   💰 {balance:,} so'm\n"
                message += f"   📝 {debt['reason']}\n"
                message += f"   📅 {debt['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n"
        message += f"💰 *Jami:*\n"
        message += f"❌ Men to'lashim kerak: {total_owe:,} so'm\n"
        message += f"✅ Menga to'lashlari kerak: {total_owed:,} so'm\n"
        message += f"📊 Balans: {(total_owed - total_owe):+,} so'm"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def show_i_owe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show debts where user is the debtor"""
        user_id = update.effective_user.id
        debts = self.db.get_debts_i_owe(user_id)
        
        if not debts:
            await update.message.reply_text("💰 Sizda to'lash uchun qarzlar yo'q! 🎉")
            return
        
        message = "💰 *Men qarzdorman:*\n\n"
        total = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            total += balance
            message += f"🔴 *#{debt['id']}* {debt['creditor_name']}ga\n"
            message += f"   💵 {balance:,} so'm\n"
            message += f"   📝 {debt['reason']}\n"
            message += f"   📅 {debt['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n"
        message += f"💰 Jami: {total:,} so'm"
        
        # Add payment buttons for each debt
        keyboard = []
        for debt in debts[:5]:  # Show up to 5 debts
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
        
        message = "💵 *Menga qarzlar:*\n\n"
        total = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            total += balance
            message += f"🟢 *#{debt['id']}* {debt['debtor_name']}dan\n"
            message += f"   💵 {balance:,} so'm\n"
            message += f"   📝 {debt['reason']}\n"
            message += f"   📅 {debt['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n"
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
        
        stats_message = (
            "📊 *Statistika:*\n\n"
            f"📈 Faol qarzlar: {active_count}\n"
            f"🕐 Kutilmoqda: {pending_count}\n"
            f"✅ To'langan: {paid_count}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💰 *Moliyaviy holat:*\n"
            f"❌ Men qarzdorman: {total_owe:,} so'm\n"
            f"✅\n"
        )