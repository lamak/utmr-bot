import re
import os
import logging
import xml.etree.ElementTree as ET
import requests
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from settings import *


logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

updater = Updater(token=telegram_token)
dispatcher = updater.dispatcher
xml_query = 'query.xml'

def fast_get(server_name: str):
    server_domain_name = server_name + domain
    url = 'http://{0}:8080/diagnosis'.format(server_domain_name)
    try:
        for x in ET.fromstring(requests.get(url, timeout=2).text).findall('CN'):
            fsrar = server_name + ' OK'
    except requests.ConnectionError:
        fsrar = server_name + ' error'
    except requests.ReadTimeout:
        fsrar = server_name + ' timeout'
    return fsrar


def fsrar_get(server_name: str):
    fsrar, error = '', ''
    server_domain_name = server_name + domain
    url = 'http://{0}:8080/diagnosis'.format(server_domain_name)
    try:
        for x in ET.fromstring(requests.get(url, timeout=2).text).findall('CN'):
            fsrar = x.text
    except (requests.ConnectionError, requests.ReadTimeout):
        # if os.system('ping %s -c 2 > NUL' % (server_domain_name,)):
        if os.system('ping %s -n 2 > NUL' % (server_name,)):
            error = 'Пинга нет'
        else:
            error = 'Пинг есть, УТМ недоступен'
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
    url = 'http://' + server_name + domain + ':8080/opt/in/QueryClients_v2'
    try:
        files = {'xml_file': (xml_query, open(xml_query, 'rb'), 'application/xml')}
        r = requests.post(url, files=files)
        if ET.fromstring(r.text).iter('sign'):
            status = 'OK'
        for error in ET.fromstring(r.text).iter('error'):
            status = error.text + ', проверьте токен'
    except:
        status = 'Не удалось отправить XML'
    return status


def startCommand(bot, update):
    bot.send_message(chat_id=update.message.chat_id,
                     text='Введите сервер с утм для проверки')


def statusCommand(bot, update):
    raw_data = []
    for server in utm:
        raw_data.append(fast_get(server))
    results = '\n'.join([i for i in raw_data])
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
        response = ' '.join([utm_server, step1, step2, step3])
    else:
        response = 'Попробуйте короткое DNS имя, например vl44-srv03'
    bot.send_message(chat_id=update.message.chat_id, text=response)


start_command_handler = CommandHandler('start', startCommand)
status_command_handler = CommandHandler('status', statusCommand)
text_message_handler = MessageHandler(Filters.text, textMessage)

dispatcher.add_handler(start_command_handler)
dispatcher.add_handler(text_message_handler)
dispatcher.add_handler(status_command_handler)

updater.start_polling(clean=True)

updater.idle()
