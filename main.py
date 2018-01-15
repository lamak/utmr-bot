from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from settings import *
import xml.etree.ElementTree as ET
import requests
import os
import logging
import re


logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

updater = Updater(token=telegram_token)
dispatcher = updater.dispatcher


def fsrar_get(server_name: str):
    fsrar, comment = '', ''
    url = 'http://' + server_name + domain + ':8080/diagnosis'
    try:
        for x in ET.fromstring(requests.get(url, timeout=1).text).findall('CN'):
            fsrar = x.text
    except requests.ConnectionError:
        server_domain_name = server_name + domain
        # if os.system('ping %s -n 4 > NUL' % (server_name,)):
        if os.system('ping %s -c 2 > NUL' % (server_domain_name,)):
            comment = 'Пинга нет'
        else:
            comment = 'Пинг есть, УТМ недоступен'
        # comment = 'УТМ недоступен'
    return fsrar, comment


def xml_make(fsrar: str):
    comment = ''
    if len(fsrar) > 1:
        try:
            tree = ET.parse(xml_query)
            root = tree.getroot()
            root[0][0].text, root[1][0][0][0][1].text = fsrar, fsrar
            tree.write(xml_query)
        except:
            comment = 'Не удалось сформировать XML'
    return comment


def xml_send(server_name: str):
    status, comment = '', ''
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
                     text='Напиши сервер с УТМ, я проверю статус')


def textMessage(bot, update):
    utm_server = update.message.text
    pattern = re.compile(re_pattern)
    if pattern.match(utm_server):
        step1, step2,status = '','',''
        fsrarid, step1 = fsrar_get(utm_server)
        if len(fsrarid) > 1:
            step2 = xml_make(fsrarid)
            status = xml_send(utm_server)
            response = update.message.text + ' ' + fsrarid + ' ' + step1 + ' ' + step2 + ' ' + status
    else:
        response = 'Попробуйте короткое DNS имя, например vl44-srv03'
    bot.send_message(chat_id=update.message.chat_id, text=response)


start_command_handler = CommandHandler('start', startCommand)
text_message_handler = MessageHandler(Filters.text, textMessage)

dispatcher.add_handler(start_command_handler)
dispatcher.add_handler(text_message_handler)

updater.start_polling(clean=True)

updater.idle()
