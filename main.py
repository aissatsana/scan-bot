import telebot
from telebot import types 
import requests
from bs4 import BeautifulSoup
import cv2
# from pyzbar.pyzbar import decode
import os
#from config import login, password, bot_token
login = os.getenv("LOGIN")
password = os.getenv("PASSWORD")
bot_token = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(bot_token)
login_url = 'https://mng.tkt.ge/Auth/Login'
events_url = 'https://mng.tkt.ge/events'
payload = {
    'UserName': login,
    'Password': password
}
events_data_id = {}
tickets = []
used_tickets = []
bot_session = None
authenticated = False

def authenticate(session):
    response = session.get(login_url, proxies=None) # Получаем страницу входа для получения CSRF-токена
    soup = BeautifulSoup(response.text, 'html.parser')
    csrf_token = soup.find('input', {'name': '__RequestVerificationToken'})['value']  # Находим CSRF-токен

    payload['__RequestVerificationToken'] = csrf_token  # Добавляем CSRF-токен в payload

    response = session.post(login_url, data=payload)
    
    if response.ok:
        print('Аутентификация прошла успешно')
        return True
    else:
        print('Ошибка при аутентификации:', response.status_code)
        return False

def load_events(session):
    response_events = session.get(events_url, proxies=None)
    if response_events.ok:
        print('Загрузка страницы событий прошла успешно')
        # Парсим HTML-код страницы событий
        soup_events = BeautifulSoup(response_events.text, 'html.parser')
        table_rows = soup_events.find_all('tr')
        
        # Выводим информацию о событиях и сохраняем data-id
        events = []
        for row in table_rows:
            data_id = row.get('data-id')
            if data_id:
                cells = row.find_all('td')
                if len(cells) >= 6 and cells[6].text.strip() != "არააქტიური":
                    event_info = f"{cells[0].text.strip()} - {cells[1].text.strip()}"
                    #здесь должен быть переводчик но у меня нет денег
                    events.append(event_info)
                    events_data_id[event_info] = data_id  # Сохраняем data-id для события
        return events
    else:
        print('Ошибка при загрузке страницы событий:', response_events.status_code)
        return None

def authenticate_and_load_events():
    global bot_session, authenticated
    if bot_session is None or not authenticated:  # Если сессия еще не создана или не аутентифицирована
        bot_session = requests.Session()
        authenticated = authenticate(bot_session)  # Выполняем аутентификацию
    if authenticated:
        return load_events(bot_session)
    else:
        print('Ошибка при аутентификации')
        return None

        
def parse_event_info(session, data_id):
    event_url = f"https://mng.tkt.ge/Events/Edit/{data_id}"
    response = session.get(event_url, proxies=None)
    if response.ok:
        soup = BeautifulSoup(response.text, 'html.parser')
        #Находим название мероприятия
        event_name = soup.find(class_="caption-subject").text.strip()
        
        # Находим количество билетов
        ticket_count_tag = soup.find(class_="js-total-count")
        ticket_count = ticket_count_tag['data-totalcount'] if ticket_count_tag else 0

        # Формируем сообщение с информацией о событии и клавиатурой
        message_text = f"{event_name}\nКоличество билетов: {ticket_count}"
        return message_text
    else:
        print('Ошибка при загрузке информации о событии')
        return None

# Обработчик команды /events
@bot.message_handler(commands=['events'])
def handle_events(message):
    events = authenticate_and_load_events()
    if events:
        # Создаем клавиатуру с inline-кнопками для списка событий
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for event in events:
            button_callback_data = f"events_{events_data_id[event]}" # Задаем данные, которые будут отправлены при нажатии кнопки
            button = types.InlineKeyboardButton(text=event, callback_data=button_callback_data)
            keyboard.add(button)
        bot.send_message(message.chat.id, 'Выберите событие из списка:', reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id, 'Ошибка при загрузке списка событий')

# Обработчик нажатия на событие
@bot.callback_query_handler(func=lambda call: call.data.startswith('events_'))
def handle_event_click(call):
    data_id = call.data.split('_')[1]  
    if data_id in events_data_id.values():
        if authenticated:
            message = parse_event_info(bot_session, data_id)
            if message:
                # Создаем клавиатуру с кнопкой "Сканировать билеты"
                keyboard = types.InlineKeyboardMarkup(row_width=1)
                button_text = "Сканировать билеты"
                button_callback_data = f"scan_tickets_{data_id}"  # Используем data-id для идентификации события
                button = types.InlineKeyboardButton(text=button_text, callback_data=button_callback_data)
                keyboard.add(button)
                bot.send_message(call.message.chat.id, message, reply_markup=keyboard)
            else:
                bot.send_message(call.message.chat.id, 'Ошибка при загрузке информации о событии')
        else:
            bot.send_message(call.message.chat.id, 'Ошибка при аутентификации')
    else:
        bot.send_message(call.message.chat.id, 'Выберите событие из списка /events')

@bot.callback_query_handler(func=lambda call: call.data.startswith('scan_tickets'))
def handle_scan_tickets(call):
    data_id = call.data.split('_')[2] 
    if data_id in events_data_id.values() and authenticated:
        scan_tickets(bot_session, data_id)
        if tickets:
            bot.send_message(call.message.chat.id, 'Начинаем сканирование билетов...')
            #on condition scanning tickets
        else:
            bot.send_message(call.message.chat.id, 'На странице мероприятия не найдены билеты')
    else:
        bot.send_message(call.message.chat.id, 'Something went wrong')

def scan_tickets(session, data_id):
    event_url = f"https://mng.tkt.ge/Events/Edit/{data_id}"
    response = session.get(event_url, proxies=None)
    if response.ok:
        soup = BeautifulSoup(response.text, 'html.parser')
        ticket_table = soup.find('table', {'class': 'table'})
        if ticket_table:
            rows = ticket_table.find_all('tr', {'data-id': True}) 
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 6:
                    ticket_status = cells[5].text.strip()
                    tickets.append(ticket_status)
        else:
            print('На странице мероприятия не найдена таблица с билетами')
            return None
    else:
        print('Ошибка при загрузке информации о событии')
        return None
           
@bot.message_handler(commands=['first_three_tickets'])
def show_first_three_tickets(message):
    chat_id = message.chat.id
    if tickets:
        first_three_tickets = tickets[:3]  # Получаем первые три номера билетов
        response = "Первые три номера билетов:\n" + "\n".join(first_three_tickets)
        bot.reply_to(message, response)
    else:
        bot.reply_to(message, 'Билетов пока нет.')

@bot.message_handler(commands=['clear_tickets'])
def clear_tickets(message):
    global tickets, used_tickets  
    if tickets:
        tickets = []  
        used_tickets = [] 
        bot.reply_to(message, 'Списки билетов очищены')
    else:
        bot.reply_to(message, 'Списки билетов уже пустые')


@bot.message_handler(commands=['stats'])
def show_stats_tickets(message):
    chat_id = message.chat.id
    if tickets:
        remaining_tickets = len(tickets) - len(used_tickets)
        response = f"Всего билетов: {len(tickets)}\nПришло гостей: {len(used_tickets)}\nОсталось: {remaining_tickets}"
        bot.reply_to(message, response)
    else:
        bot.reply_to(message, "Нет информации о билетах.")



def check_ticket_status(ticket_number):
    if tickets:  # Проверяем, есть ли билеты в базе данных
        for ticket in tickets:
            if ticket_number in ticket[:5]:
                current_ticket = ticket
                if current_ticket not in used_tickets:
                    used_tickets.append(current_ticket)  # Помечаем билет как использованный
                    return f'Билет: {ticket}\nСтатус билета: Активен'
                else:
                    return f'Билет: {ticket}\nСтатус билета: Был использован'
        return f'Билет: {ticket_number}\nСтатус билета: Не найден'
    else:
        return 'Билеты не найдены'

@bot.message_handler(func=lambda message: len(message.text) == 5)
def check_ticket(message):
    chat_id = message.chat.id
    ticket_number = message.text 
    response = check_ticket_status(ticket_number)
    bot.reply_to(message, response)


# @bot.message_handler(content_types=['photo'])
# def handle_photo(message):
#     try:
#         # Получаем информацию о фотографии
#         file_info = bot.get_file(message.photo[-1].file_id)
#         downloaded_file = bot.download_file(file_info.file_path)

#         # Сохраняем фотографию на диск
#         with open("photo.jpg", 'wb') as new_file:
#             new_file.write(downloaded_file)

#         # Загружаем фотографию и конвертируем ее в массив numpy
#         img = cv2.imread("photo.jpg")
        
#         # Преобразуем изображение в оттенки серого
#         gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
#         # Распознаем QR-коды на фотографии
#         decoded_objects = decode(gray_img)
        
#         # Отправляем результаты распознавания
#         if decoded_objects:
#             for obj in decoded_objects:
#                 ticket_number = obj.data.decode('utf-8')
#                 response = check_ticket_status(ticket_number)
#                 bot.reply_to(message, response)
#         else:
#             bot.send_message(message.chat.id, "На фотографии не обнаружены QR-коды.")
#     except Exception as e:
#         print(e)
#         bot.send_message(message.chat.id, "Произошла ошибка при обработке фотографии.")



bot.polling()