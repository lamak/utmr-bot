from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import xml.etree.ElementTree as ET
import requests
import os

#updater = Updater(token='your_token_here')

dispatcher = updater.dispatcher

xml_query = 'query.xml'


def fsrar_get(server_name: str):
    fsrar, comment = '', ''
    url = 'http://' + server_name + ':8080/diagnosis'
    try:
        for x in ET.fromstring(requests.get(url).text).findall('CN'):
            fsrar = x.text
    except requests.ConnectionError:
        if os.system('ping %s -n 4 > NUL' % (server_name,)):
            comment = 'Пинга нет'
        else:
            comment = 'Пинг есть'
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
    url = 'http://' + server_name + ':8080/opt/in/QueryClients_v2'
    try:
        files = {'xml_file': (xml_query, open(xml_query, 'rb'), 'application/xml')}
        r = requests.post(url, files=files)
        if ET.fromstring(r.text).iter('sign'):
            status = 'OK'
        for error in ET.fromstring(r.text).iter('error'):
            status = 'Ошибка подписи, проверьте ключ' + error.text
    except:
        status = 'Не удалось отправить XML'
    return status


def startCommand(bot, update):
    bot.send_message(chat_id=update.message.chat_id,
                     text='Напиши сервер с УТМ, я проверю статус')


def textMessage(bot, update):
    utm_server = update.message.text
    fsrarid, step1 = fsrar_get(utm_server)
    step2 = xml_make(fsrarid)
    status = xml_send(utm_server)
    response = update.message.text + ' ' + fsrarid + ' ' + step1 + ' ' + step2 + ' ' + status
    bot.send_message(chat_id=update.message.chat_id, text=response)


start_command_handler = CommandHandler('start', startCommand)
text_message_handler = MessageHandler(Filters.text, textMessage)

dispatcher.add_handler(start_command_handler)
dispatcher.add_handler(text_message_handler)

updater.start_polling(clean=True)

updater.idle()