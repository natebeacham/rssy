import math
import json
import time
import random
import string
import smtplib
import datetime
import premailer
import threading
import feedparser

import redis as redispy

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, session, redirect, \
	url_for, request, render_template

app = Flask(__name__)
app.config.from_pyfile('config.cfg')

redis = redispy.StrictRedis(
	host='localhost',
	port=6379,
	db=1
)

PER_PAGE = 10

class DB(object):
	prefix = 'rssdb:'

	def clear(self):
		redis.delete("%sfeeds" % self.prefix)
		redis.delete("%sentries" % self.prefix)
		redis.delete("%smemo" % self.prefix)

	def push_feed(self, url):
		if not redis.sismember("%sfeeds" % self.prefix, url):
			redis.sadd("%sfeeds" % self.prefix, url)

	def push_entry(self, url, feed, entry):
		memokey = "%s:%s" % (url, entry['id'])

		if not redis.hexists("%smemo" % self.prefix, memokey):
			redis.hset("%smemo" % self.prefix, memokey, '1')

			data = {
				'title': entry['title'],
				'link': entry['link'],
				'tags': ', '.join([tag.get('term') for tag in entry.get('tags', [])]),
				'author': entry.get('author'),
				'summary': entry.get('summary_detail', {})\
					.get('value', '').encode('utf-8'),
				'feed': feed['title'],
			}

			if 'published_parsed' in entry:
				data['timestamp'] = datetime.datetime.fromtimestamp(
					time.mktime(entry['published_parsed'])
				).strftime('%m/%d/%Y - %r')
			else:
				data['timestamp'] = datetime.datetime.now()\
					.strftime('%m/%d/%Y - %r')

			redis.lpush("%sentries" % self.prefix, json.dumps(data))

			self.notify(data)

	def populate_feed(self, url):
		items = feedparser.parse(url)

		feed = items['feed']

		for entry in items['entries']:
			self.push_entry(url, feed, entry)

	def notify(self, entry):
		con = smtplib.SMTP("smtp.gmail.com:587")
		con.starttls()

		try:
		        con.login(app.config['GMAIL_USER'], app.config['GMAIL_PASSWORD'])
		except Exception, e:
		        print e
		        con = None

		if con:
			with app.test_request_context('/'):
				rendered = premailer.transform(
					render_template('mail.html',
						entry=entry,
					)
				)

			for email in app.config['EMAILS']:
				msg = MIMEMultipart('alternative')
				msg['Subject'] = (u'rssy | %s:  %s' % (entry['feed'], entry['title'])).encode('utf-8')
				msg['From'] = app.config['FROM']
				msg['To'] = email

				msg.attach(MIMEText(entry['summary'], 'plain'))
				msg.attach(MIMEText(rendered, 'html'))

				con.sendmail(app.config['FROM'], [email], msg.as_string())

	def __getitem__(self, sl):
		if not isinstance(sl, slice):
			raise NotImplementedError

		return redis.lrange("%sentries" % self.prefix, sl.start, sl.stop)

	def __len__(self):
		return redis.llen("%sentries" % self.prefix)

	def __iter__(self):
		for url in redis.smembers("%sfeeds" % self.prefix):
			yield url

	def page(self, page_num):
		lbound = (page_num - 1) * PER_PAGE
		rbound = lbound + PER_PAGE

		for item in self[lbound:rbound]:
			yield json.loads(item)

	def page_range(self):
		return range(1, int(math.ceil(float(len(self)) / PER_PAGE)) + 1)

db = DB()

class PopulationThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self, target=self.populate)
		self.daemon = True

	def populate(self):
		while True:
			for url in db:
				db.populate_feed(url)

			time.sleep(3600)

def get_session_key():
	return ''.join(random.choice(string.ascii_letters) for x in range(1,24))

def is_authenticated():
	sessionid = session.get('sessionid')

	return not (sessionid is None or not redis.hexists('sessions', sessionid))

def login_required(func):
	def inner():
		sessionid = session.get('sessionid')
		if not is_authenticated():
			return redirect('/auth/?next=%s' % request.path)
		return func()
	return inner

@app.route('/')
def index():
	try:
		page_num = int(request.args.get('p', 1))
	except (TypeError, ValueError):
		page_num = 1

	return render_template('index.html',
		items=db.page(page_num),
		db=db,
		page_num=page_num,
		is_authenticated=is_authenticated(),
	)

@app.route('/auth/', methods=['GET', 'POST'])
def login():
	next = request.args.get('next', request.form.get('next'))

	if request.method == "POST":
		username = request.form.get('username')
		password = request.form.get('password')

		if username and password:
			if username == app.config['USERNAME'] and password == app.config['PASSWORD']:
				sessionkey = get_session_key()
				session['sessionid'] = sessionkey
				redis.hset('sessions', sessionkey, '1')

				if next:
					return redirect(next)

				return redirect('/')

	return render_template('login.html',
		next=next,
		is_authenticated=is_authenticated(),
	)

@app.route('/logout/', methods=['GET'])
def logout():
	if not is_authenticated():
		return redirect('/')

	sessionkey = session['sessionid']

	del session['sessionid']
	redis.hdel('sessions', sessionkey)

	return redirect('/')

@app.route('/add/', methods=['GET', 'POST'])
@login_required
def add_feed():
	if request.method == "POST":
		url = request.form.get("url")

		if url:
			db.push_feed(url)
			db.populate_feed(url)

			return redirect('/')

	return render_template('add.html', is_authenticated=is_authenticated(),)

@app.errorhandler(404)
def page_not_found(e):
	return render_template('404.html'), 404

for feed in app.config['FEEDS']:
	db.push_feed(feed)
	populator = PopulationThread()
	populator.start()

if __name__ == '__main__':
	app.run(host='0.0.0.0', port=4004)
