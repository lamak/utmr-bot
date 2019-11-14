import re
import os
import logging
import xml.etree.ElementTree as ET
import requests
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import socks

domain = '.severotorg.local'
telegram_token = '489249497:AAGrMKgiadMb5-pUxpbBxH-shEFK8ebV9es'
proxy = {
    'proxy_url': 'socks5://3.112.68.29:3480',
    # 'urllib3_proxy_kwargs': {
    #     'username': 'name',
    #     'password': 'pass',
    # }
}
re_pattern = "\w+[-]\w+"

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

updater = Updater(token=telegram_token, request_kwargs=proxy)
dispatcher = updater.dispatcher
xml_query = 'query.xml'
xml_wb = 'wb.xml'


def fast_get(server_name: str):
    server_domain_name = server_name + domain
    url = 'http://{0}:8080/diagnosis'.format(server_domain_name)
    # url_version = 'http://{0}:8080/info/version'.format(server_domain_name)
    try:
        # version = requests.get(url_version, timeout=2).text
        cn = ET.fromstring(requests.get(url).text).find('CN').text
        fsrar = 'OK [' + cn +'] ' + server_name
    except requests.ConnectionError:
        fsrar = server_name + ' **error**'
    except requests.ReadTimeout:
        fsrar = server_name + ' **timeout**'
    except ET.ParseError:
        fsrar = server_name + ' **no token**'
    return fsrar


def fsrar_get(server_name: str):
    fsrar, error = '', ''
    server_domain_name = server_name + domain
    url = 'http://{0}:8080/diagnosis'.format(server_domain_name)
    try:
        fsrar = ET.fromstring(requests.get(url).text).find('CN').text
    except (requests.ConnectionError, requests.ReadTimeout):
        # if os.system('ping %s -c 2 > NUL' % (server_domain_name,)):
        if os.system('ping %s -n 2 > NUL' % (server_name,)):
            error = 'Связи нет'
        else:
            error = 'Связь есть, УТМ недоступен'
    except ET.ParseError:
        error = 'Проблема с УТМ, проверьте Рутокен'
    return fsrar, error


def xml_make(fsrar: str):
    error = ''
    if fsrar:
        try:
            tree = ET.parse(xml_query)
            root = tree.getroot()
            root[0][0].text, root[1][0][0][0][1].text = fsrar, fsrar
            tree.write(xml_query)
        except:
            error = 'Не удалось сформировать XML'
    return error


def xml_send(server_name: str):
    status = ''
    server_domain_name = server_name + domain
    url = 'http://{0}:8080/opt/in/QueryClients_v2'.format(server_domain_name)
    try:
        files = {'xml_file': (xml_query, open(
            xml_query, 'rb'), 'application/xml')}
        r = requests.post(url, files=files)
        if ET.fromstring(r.text).iter('sign'):
            status = 'OK'
        for error in ET.fromstring(r.text).iter('error'):
            status = error.text + ', **проверьте токен**'
    except:
        status = '**Не удалось отправить XML**'
    return status


def filterCommand(bot, update):
    with open("utms") as f: 
        data = f.read().splitlines()
    raw_data = []
    for server in data:
        status, error = '', ''
        server_domain_name = server + domain
        url = 'http://{0}:8080/xhr/filter/reset'.format(server_domain_name)
        try:
            result = requests.get(url, timeout=20).text
        except requests.exceptions.ReadTimeout:
            result = 'ConnectionError'
        raw_data.append(server + " " + result)
    results = '\n'.join([i for i in raw_data])
    bot.send_message(chat_id=update.message.chat_id,
                     text=results)


def startCommand(bot, update):
    bot.send_message(chat_id=update.message.chat_id,
                     text='Введите сервер с утм для проверки')


def helpCommand(bot, update):
    help_text = ''
    with open('help.txt', 'r', encoding='utf-8') as file:
        help_text = file.read()
    bot.send_message(chat_id=update.message.chat_id,
                     text=help_text, parse_mode='Markdown')


def faqCommand(bot, update):
    faq_text = ''
    with open('faq.txt', 'r', encoding='utf-8') as file:
        faq_text = file.read()
    bot.send_message(chat_id=update.message.chat_id,
                     text=faq_text, parse_mode='Markdown')


def statusCommand(bot, update):
    with open("utms") as f: 
        data = f.read().splitlines()
    raw_data = []
    for server in data:
        raw_data.append(fast_get(server))
    results = '\n'.join(raw_data)
    bot.send_message(chat_id=update.message.chat_id,
                     text=results)


def textMessage(bot, update):
    utm_server = update.message.text
    pattern = re.compile(re_pattern)
    if pattern.match(utm_server):
        fsrarid, step1, step2, step3 = '', '', '', ''
        fsrarid, step1 = fsrar_get(utm_server)
        if fsrarid:
            step2 = xml_make(fsrarid)
            step3 = xml_send(utm_server)
        response = ' '.join([utm_server, fsrarid, step1, step2, step3])
    else:
        response = 'Попробуйте короткое DNS имя, например vl44-srv03'
    bot.send_message(chat_id=update.message.chat_id, text=response)


start_command_handler = CommandHandler('start', startCommand)
status_command_handler = CommandHandler('status', statusCommand)
help_command_handler = CommandHandler('help', helpCommand)
faq_command_handler = CommandHandler('faq', faqCommand)
text_message_handler = MessageHandler(Filters.text, textMessage)
filter_command_handler = CommandHandler('filter', filterCommand)


dispatcher.add_handler(start_command_handler)
dispatcher.add_handler(text_message_handler)
dispatcher.add_handler(help_command_handler)
dispatcher.add_handler(faq_command_handler)
dispatcher.add_handler(status_command_handler)
dispatcher.add_handler(filter_command_handler)


updater.start_polling(clean=True)

updater.idle()
