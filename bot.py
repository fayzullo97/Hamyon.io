import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from openai import OpenAI
import httpx
from datetime import datetime
import json
import re
from database import Database

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
class DebtBot:
    def __init__(self):
        self.db = db
        self.pending_debts = {}
        self.user_context = {}
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.create_user(user.id, user.username, user.first_name, user.last_name)
        
        keyboard = [[KeyboardButton("📊 Mening qarzlarim"), KeyboardButton("💰 Men qarzdorman")],
                    [KeyboardButton("💵 Menga qarzlar"), KeyboardButton("📜 Tarix")],
                    [KeyboardButton("ℹ️ Yordam"), KeyboardButton("📊 Statistika")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_text = (f"👋 Salom, {user.first_name}!\n\n"
                       "Men Telegram orqali qarzlar va umumiy xarajatlarni boshqarish botiman.\n\n"
                       "🎤 *Ovozli xabar yuboring* va men:\n"
                       "• Qarz yoki xarajatni qayd qilaman\n"
                       "• Ishtirokchilarni bog'layman\n"
                       "• Tasdiqlash so'rayman\n"
                       "• Barcha ishtirokchilarga xabar beraman\n\n"
                       "📝 *Misollar:*\n"
                       '• "Alisher menga 50 ming so\'m qarz berdi lunch uchun"\n'
                       '• "Men Dilnozaga 100 ming so\'m qarz berdim"\n\n'
                       "Ovozli xabar yuboring!")
        
        await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = ("📖 *Yordam*\n\n"
                    "*Qarz yaratish:*\n"
                    "🎤 Ovozli xabar yuboring\n\n"
                    "*Tugmalar:*\n"
                    "📊 Mening qarzlarim - Barcha qarzlar\n"
                    "💰 Men qarzdorman - Men to'lashim kerak\n"
                    "💵 Menga qarzlar - Menga to'lashlari kerak\n"
                    "📜 Tarix - To'liq tarix\n"
                    "📊 Statistika - Statistika")
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        processing_msg = await update.message.reply_text("🎤 Ovozli xabaringizni tinglayapman...")
        
        try:
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)
            voice_path = f"voice_{user.id}_{datetime.now().timestamp()}.ogg"
            await file.download_to_drive(voice_path)
        
            with open(voice_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(model="whisper-1",file=audio_file)
            transcribed_text = transcript.text
            if os.path.exists(voice_path):
                os.remove(voice_path)
            
            await processing_msg.edit_text(f"📝 Matn: _{transcribed_text}_\n\n⏳ Tahlil qilyapman...", parse_mode='Markdown')
            
            debt_info = await self.parse_debt_info(transcribed_text, user)
            
            if debt_info.get('error'):
                await processing_msg.edit_text(f"❌ {debt_info['error']}\n\nIltimos, qaytadan urinib ko'ring.")
                return
            
            missing = self.check_missing_info(debt_info)
            if missing:
                await self.request_missing_info(update, context, debt_info, missing, processing_msg)
                return
            
            await self.create_debt_confirmation(update, context, debt_info, processing_msg)
            
        except Exception as e:
            logger.error(f"Error processing voice: {e}")
            await processing_msg.edit_text(f"❌ Xatolik yuz berdi: {str(e)[:100]}")
    
    async def parse_debt_info(self, text: str, user):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": """Sen qarz tahlilchisan. JSON qaytaring:
                    - amount: raqam (50 ming = 50000)
                    - currency: "so'm"
                    - creditor_name: kim qarz berdi
                    - debtor_name: kim qarz oldi
                    - reason: sabab
                    - direction: "i_owe" yoki "owe_me"
                    
                    "menga qarz berdi" = owe_me
                    "men qarz berdim" = i_owe"""},
                    {"role": "user", "content": text}
                ],
                temperature=0.3
            )
            
            content = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:].strip()
            
            result = json.loads(content)
            result['original_text'] = text
            return result
        except Exception as e:
            logger.error(f"Parse error: {e}")
            logger.error(f"Full error details: {type(e).__name__}: {str(e)}")
            return {'error': f'Tushunmadim. Xato: {str(e)[:50]}'}
    
    def check_missing_info(self, debt_info):
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
        questions = {
            'amount': "💰 Qancha pul? (masalan: 50000)",
            'creditor_name': "👤 Kim qarz berdi?",
            'debtor_name': "👤 Kimga qarz berdingiz?",
            'direction': "❓ Kim kimga qarz berdi?",
            'reason': "📝 Nima uchun?"
        }
        
        self.user_context[update.effective_user.id] = {
            'debt_info': debt_info,
            'missing': missing,
            'step': 0,
            'message_id': processing_msg.message_id
        }
        
        question_text = questions.get(missing[0], "Ma'lumot kerak")
        await processing_msg.edit_text(f"❓ {question_text}")
    
    async def create_debt_confirmation(self, update, context, debt_info, processing_msg):
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
        
        confirmation_text = ("✅ *Tasdiqlash kerak:*\n\n"
                           f"💰 Summa: {debt_info['amount']:,} so'm\n"
                           f"📝 Sabab: {debt_info.get('reason', 'Sababsiz')}\n"
                           f"👤 Qarz beruvchi: {creditor_name}\n"
                           f"👤 Qarz oluvchi: {debtor_name}\n\n")
        
        if not other_user:
            confirmation_text += "⚠️ Foydalanuvchi topilmadi. @username yoki kontakt ulashing.\n\n"
        
        confirmation_text += "Bu to'g'rimi?"
        
        keyboard = [[InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{debt_id}"),
                    InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_{debt_id}")]]
        
        if not other_user:
            keyboard.append([InlineKeyboardButton("🔍 Username", callback_data=f"adduser_{debt_id}")])
        
        await processing_msg.edit_text(confirmation_text, parse_mode='Markdown', 
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        elif data.startswith('adduser_'):
            await self.adduser_callback(query, data)
        elif data.startswith('remind_'):
            await self.send_reminder_callback(query, data)
    
    async def confirm_debt_callback(self, query, data):
        debt_id = data.replace('confirm_', '')
        
        if debt_id not in self.pending_debts:
            await query.edit_message_text("❌ Qarz topilmadi.")
            return
        
        debt_data = self.pending_debts[debt_id]
        
        if not debt_data.get('creditor_id') or not debt_data.get('debtor_id'):
            await query.edit_message_text("❌ Ikkinchi foydalanuvchi topilmadi.")
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
        
        other_user_id = (debt_data['debtor_id'] if debt_data['creator_id'] == debt_data['creditor_id'] 
                        else debt_data['creditor_id'])
        
        notification_text = ("🔔 *Yangi qarz*\n\n"
                           f"💰 Summa: {debt_data['amount']:,} so'm\n"
                           f"📝 Sabab: {debt_data['reason']}\n\n"
                           "Iltimos, tasdiqlang:")
        
        keyboard = [[InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"accept_debt_{created_debt_id}"),
                    InlineKeyboardButton("❌ E'tiroz", callback_data=f"dispute_debt_{created_debt_id}")]]
        
        try:
            await query.get_bot().send_message(
                chat_id=other_user_id,
                text=notification_text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            await query.edit_message_text(
                f"✅ Qarz yaratildi!\n\n"
                f"💰 {debt_data['amount']:,} so'm\n"
                f"📝 {debt_data['reason']}\n\n"
                "Xabarnoma yuborildi.",
                parse_mode='Markdown'
            )
            
            self.db.create_notification(other_user_id, created_debt_id, notification_text, 'debt_created')
            
        except Exception as e:
            logger.error(f"Notification error: {e}")
            await query.edit_message_text("⚠️ Qarz yaratildi, lekin xabarnoma yuborilmadi.")
        
        del self.pending_debts[debt_id]
    async def adduser_callback(self, query, data):
        """Handle adding username for pending debt"""
        debt_id = data.replace('adduser_', '')
        
        if debt_id not in self.pending_debts:
            await query.edit_message_text("❌ Qarz topilmadi yoki muddati o'tgan.")
            return
        
        # Store the debt_id in user context
        self.user_context[query.from_user.id] = {
            'action': 'add_username',
            'debt_id': debt_id
        }
        
        await query.message.reply_text(
            "👤 Foydalanuvchi username kiriting:\n\n"
            "Masalan: @fayzkhanov\n\n"
            "Yoki kontakt ulashing."
        )
    async def accept_debt_callback(self, query, data):
        debt_id = int(data.replace('accept_debt_', ''))
        user_id = query.from_user.id
        
        if self.db.confirm_debt(debt_id, user_id):
            debt = self.db.get_debt(debt_id)
            
            if debt and debt['status'] == 'active':
                await query.edit_message_text(
                    f"✅ Qarz tasdiqlandi!\n\n"
                    f"💰 {debt['amount']:,} so'm\n"
                    f"📝 {debt['reason']}",
                    parse_mode='Markdown'
                )
                
                try:
                    await query.get_bot().send_message(
                        chat_id=debt['creator_id'],
                        text=f"✅ {debt['amount']:,} so'm qarzingiz tasdiqlandi!"
                    )
                except:
                    pass
            else:
                await query.edit_message_text("✅ Tasdiqingiz qayd qilindi.")
        else:
            await query.edit_message_text("❌ Xatolik.")
    
    async def dispute_debt_callback(self, query, data):
        debt_id = int(data.replace('dispute_debt_', ''))
        debt = self.db.get_debt(debt_id)
        
        if debt:
            self.db.cancel_debt(debt_id, debt['creator_id'])
            await query.edit_message_text("❌ Qarz bekor qilindi.")
            
            try:
                await query.get_bot().send_message(
                    chat_id=debt['creator_id'],
                    text=f"❌ {debt['amount']:,} so'm qarzga e'tiroz bildirildi."
                )
            except:
                pass
    
    async def show_my_debts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        debts = self.db.get_user_debts(user_id)
        
        if not debts:
            await update.message.reply_text("📊 Faol qarzlar yo'q.\n\nQarz yaratish uchun ovozli xabar yuboring!")
            return
        
        message = "📊 *Mening qarzlarim:*\n\n"
        total_owe = 0
        total_owed = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            
            if debt['debtor_id'] == user_id:
                total_owe += balance
                icon = "🔴" if debt['status'] == 'active' else "🟡"
                message += f"{icon} *#{debt['id']}* Men {debt['creditor_name']}ga qarzdorman\n"
                message += f"   💰 {balance:,} so'm\n   📝 {debt['reason']}\n   📅 {debt['created_at'][:10]}\n\n"
            else:
                total_owed += balance
                icon = "🟢" if debt['status'] == 'active' else "🟡"
                message += f"{icon} *#{debt['id']}* {debt['debtor_name']} menga qarz\n"
                message += f"   💰 {balance:,} so'm\n   📝 {debt['reason']}\n   📅 {debt['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n"
        message += f"💰 *Jami:*\n"
        message += f"❌ Men to'lashim kerak: {total_owe:,} so'm\n"
        message += f"✅ Menga to'lashlari kerak: {total_owed:,} so'm\n"
        message += f"📊 Balans: {(total_owed - total_owe):+,} so'm"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def show_i_owe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        debts = self.db.get_debts_i_owe(user_id)
        
        if not debts:
            await update.message.reply_text("💰 To'lash uchun qarzlar yo'q! 🎉")
            return
        
        message = "💰 *Men qarzdorman:*\n\n"
        total = 0
        
        for debt in debts:
            balance = self.db.get_debt_balance(debt['id'])
            total += balance
            message += f"🔴 *#{debt['id']}* {debt['creditor_name']}ga\n"
            message += f"   💵 {balance:,} so'm\n   📝 {debt['reason']}\n   📅 {debt['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n💰 Jami: {total:,} so'm"
        
        keyboard = []
        for debt in debts[:5]:
            balance = self.db.get_debt_balance(debt['id'])
            if balance > 0:
                keyboard.append([InlineKeyboardButton(
                    f"💳 To'lash #{debt['id']} ({balance:,} so'm)", 
                    callback_data=f"pay_{debt['id']}"
                )])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def show_owed_to_me(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            message += f"   💵 {balance:,} so'm\n   📝 {debt['reason']}\n   📅 {debt['created_at'][:10]}\n\n"
        
        message += f"━━━━━━━━━━━━━━━━\n💰 Jami: {total:,} so'm"
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        stats_text = ("📊 *Statistika:*\n\n"
                     f"📈 Faol qarzlar: {active_count}\n"
                     f"🕐 Kutilmoqda: {pending_count}\n"
                     f"✅ To'langan: {paid_count}\n\n"
                     "━━━━━━━━━━━━━━━━\n"
                     "💰 *Moliyaviy holat:*\n"
                     f"❌ Men qarzdorman: {total_owe:,} so'm\n"
                     f"✅ Menga qarz: {total_owed:,} so'm\n"
                     f"📊 Balans: {(total_owed - total_owe):+,} so'm")
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def show_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, c.first_name as creditor_name, b.first_name as debtor_name
            FROM debts d
            JOIN users c ON d.creditor_id = c.user_id
            JOIN users b ON d.debtor_id = b.user_id
            WHERE d.creditor_id = ? OR d.debtor_id = ?
            ORDER BY d.created_at DESC LIMIT 20
        ''', (user_id, user_id))
        
        debts = cursor.fetchall()
        conn.close()
        
        if not debts:
            await update.message.reply_text("📜 Tarix bo'sh.")
            return
        
        message = "📜 *Tarix (oxirgi 20):*\n\n"
        status_emoji = {'pending': '🟡', 'active': '🔵', 'paid': '✅', 'cancelled': '❌'}
        
        for debt in debts:
            d = dict(debt)
            emoji = status_emoji.get(d['status'], '⚪')
            message += f"{emoji} *#{d['id']}* "
            
            if d['debtor_id'] == user_id:
                message += f"{d['creditor_name']}ga qarzdor\n"
            else:
                message += f"{d['debtor_name']}dan qarz\n"
            
            message += f"   💰 {d['amount']:,} so'm\n   📝 {d['reason']}\n"
            message += f"   📅 {d['created_at'][:10]}\n   Status: {d['status']}\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def send_reminder_callback(self, query, data):
        debt_id = int(data.replace('remind_', ''))
        debt = self.db.get_debt(debt_id)
        
        if not debt or debt['creditor_id'] != query.from_user.id:
            await query.edit_message_text("❌ Xatolik.")
            return
        
        balance = self.db.get_debt_balance(debt_id)
        
        if balance <= 0:
            await query.edit_message_text("✅ Qarz to'langan!")
            return
        
        reminder_text = (f"🔔 *Eslatma*\n\n"
                        f"Sizning {debt['creditor_name']}ga qarzingiz:\n"
                        f"💰 Summa: {balance:,} so'm\n"
                        f"📝 Sabab: {debt['reason']}\n"
                        f"📅 Yaratilgan: {debt['created_at'][:10]}\n\n"
                        "Iltimos, qarzni to'lashni unutmang!")
        
        try:
            await query.get_bot().send_message(chat_id=debt['debtor_id'], text=reminder_text, parse_mode='Markdown')
            await query.edit_message_text(f"✅ Eslatma yuborildi!\n\n📨 {debt['debtor_name']}ga")
            self.db.create_notification(debt['debtor_id'], debt_id, "Qarz eslatmasi", 'reminder')
        except Exception as e:
            logger.error(f"Reminder error: {e}")
            await query.edit_message_text("❌ Eslatma yuborilmadi.")
    
    async def initiate_payment(self, query, data):
        debt_id = int(data.replace('pay_', ''))
        debt = self.db.get_debt(debt_id)
        
        if not debt:
            await query.edit_message_text("❌ Qarz topilmadi.")
            return
        
        balance = self.db.get_debt_balance(debt_id)
        
        if balance <= 0:
            await query.edit_message_text("✅ Qarz to'langan!")
            return
        
        self.user_context[query.from_user.id] = {'action': 'payment', 'debt_id': debt_id, 'balance': balance}
        
        await query.message.reply_text(
            f"💳 *To'lov:*\n\n"
            f"Qarz: #{debt_id}\n"
            f"Qolgan: {balance:,} so'm\n\n"
            "Qancha to'lamoqchisiz?",
            parse_mode='Markdown'
        )
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        contact = update.message.contact
        user_id = update.effective_user.id
        
        self.db.create_user(contact.user_id, None, contact.first_name, contact.last_name)
        
        if user_id in self.user_context and 'debt_info' in self.user_context[user_id]:
            debt_ctx = self.user_context[user_id]
            debt_info = debt_ctx['debt_info']
            
            if debt_info.get('direction') == 'owe_me':
                debt_info['creditor_name'] = contact.first_name
            else:
                debt_info['debtor_name'] = contact.first_name
            
            debt_ctx['contact_user_id'] = contact.user_id
            await update.message.reply_text(f"✅ Kontakt qabul qilindi: {contact.first_name}")
        else:
            await update.message.reply_text(f"✅ Kontakt saqlandi: {contact.first_name}")
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        else:
            if user_id in self.user_context:
                await self.handle_context_response(update, context)
            else:
                await update.message.reply_text(
                    "📱 Iltimos, qarz haqida *ovozli xabar* yuboring.\n\n"
                    "Yoki quyidagi tugmalardan foydalaning:",
                    parse_mode='Markdown'
                )
    
    async def handle_context_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    await update.message.reply_text(f"❌ Summa qoldiqdan katta.\nQoldiq: {balance:,} so'm")
                    return
                
                payment_id = self.db.add_payment(debt_id, user_id, amount)
                debt = self.db.get_debt(debt_id)
                self.db.confirm_payment(payment_id)
                new_balance = self.db.get_debt_balance(debt_id)
                
                if new_balance == 0:
                    await update.message.reply_text(
                        f"✅ *To'lov qabul qilindi!*\n\n"
                        f"💵 To'langan: {amount:,} so'm\n"
                        "🎉 Qarz to'liq to'landi!",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        f"✅ *To'lov qabul qilindi!*\n\n"
                        f"💵 To'langan: {amount:,} so'm\n"
                        f"📊 Qoldiq: {new_balance:,} so'm",
                        parse_mode='Markdown'
                    )
                
                try:
                    await context.bot.send_message(
                        chat_id=debt['creditor_id'],
                        text=f"💰 {debt['debtor_name']} {amount:,} so'm to'ladi!\nQarz: #{debt_id}\nQoldiq: {new_balance:,} so'm"
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
                    await update.message.reply_text("❌ Summani tushunmadim. Raqam kiriting (masalan: 50000)")
                    return
            elif field in ['creditor_name', 'debtor_name']:
                debt_info[field] = text
            elif field == 'reason':
                debt_info['reason'] = text
            
            if step + 1 < len(missing):
                user_ctx['step'] = step + 1
                next_field = missing[step + 1]
                questions = {
                    'amount': "💰 Qancha pul?",
                    'creditor_name': "👤 Kim qarz berdi?",
                    'debtor_name': "👤 Kimga qarz berdingiz?",
                    'reason': "📝 Nima uchun?"
                }
                await update.message.reply_text(questions[next_field])
            else:
                del self.user_context[user_id]
                processing_msg = await update.message.reply_text("⏳ Qayd qilyapman...")
                await self.create_debt_confirmation(update, context, debt_info, processing_msg)

def main():
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