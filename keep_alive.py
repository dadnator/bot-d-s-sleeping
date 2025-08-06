from flask import Flask
from threading import Thread

app = Flask('')


@app.route('/')
def home():
  return "le bot est en ligne jeux dés sleeping !"


def run():
  app.run(host='0.0.0.0', port=8085)


def keep_alive():
  t = Thread(target=run)
  t.start()
