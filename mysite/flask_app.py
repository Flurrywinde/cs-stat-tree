import os
import sys
import tempfile
from rich import inspect
from rich.console import Console
from flask import Flask, redirect, url_for, request, render_template, flash, send_file
#from flask_cors import CORS
from flask import json
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from cstree import CStree
import requests
import json
from dotenv import load_dotenv

# Use venv. (Highest version on pythonanywhere is python3.9, so using this locally too.) On pythonanywhere, in shell, do `workon myvirtualenv`. Locally, `. venv/bin/activate.fish`. Install all needed modules. (See Dependencies list below.) To run flask locally: `python flask_app.py`, then in browser: `http://localhost:5000' or `http://127.0.0.1:5000/`

# Dependencies (besides cstree and ctree): flask, prompt_toolkit, networkx, pygraphviz, asteval, rich, flask_cors, requests, python-dotenv

consolef = Console(stderr=True)
#sys.setrecursionlimit(10000)
load_dotenv()  # https://stackoverflow.com/questions/51228227/standard-practice-for-wsgi-secret-key-for-flask-applications-on-github-reposito
app = Flask(__name__, static_url_path="", static_folder="static")

UPLOAD_FOLDER = os.path.join(os.path.dirname(app.root_path), 'uploads')  # maybe shouldn't just dirname these...
CSGV_FOLDER = os.path.join(os.path.dirname(app.root_path), 'choicescript-graphviz')
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'dot', 'gv'}

# TODO: proper way to config: https://stackoverflow.com/questions/17077863/how-to-see-if-a-flask-app-is-being-run-on-localhost
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 1000 * 1000	# 1 meg. Raises RequestEntityTooLarge exception.
# Set the secret key to some random bytes. Keep this really secret! See: https://stackoverflow.com/questions/51436382/runtimeerror-the-session-is-unavailable-because-no-secret-key-was-set-set-the and https://stackoverflow.com/questions/34902378/where-do-i-get-a-secret-key-for-flask
app.secret_key = os.getenv('SECRET_KEY', 'for dev')
#CORS(app, resources={r"/*": {"origins": "*"}})

tree = CStree()

def is_production():
    """ Determines if app is running on the production server or not.
    Get Current URI.
    Extract root location.
    Compare root location against developer server value 127.0.0.1:5000.
    :return: (bool) True if code is running on the production server, and False otherwise.
    """
    root_url = request.url_root
    developer_url = 'http://127.0.0.1:5000/'
    developer_url2 = 'http://localhost:5000/'
    return root_url != developer_url and root_url != developer_url2

def uploadgist(dotcode):
	GITHUB_API="https://api.github.com"
	#API_TOKEN='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'  # generate this here: https://github.com/settings/tokens/new (From: https://stackoverflow.com/questions/65518288/python-how-to-edit-update-a-github-gist (info on request.patch()))
	API_TOKEN=os.getenv('GITHUB_GIST_API_TOKEN', 'for dev') 

	#form a request URL
	url=GITHUB_API+"/gists"
	#print("Request URL: %s"%url)

	# read in file
	#with open('data.txt', 'r') as file:
	#	data = file.read()

	#print headers,parameters,payload
	gist_filename = 'cs_analysis'
	headers={'Authorization':'token %s'%API_TOKEN}
	params={'scope':'gist'}
	payload={"description":"GIST created by python code","public":True,"files":{f"{gist_filename}":{"content":f"{dotcode}"}}}

	#make a requests
	res=requests.post(url,headers=headers,params=params,data=json.dumps(payload))

	#print response --> JSON
	#print(res.status_code)
	#print(res.url)
	#print(res.text)
	j=json.loads(res.text)

	#for gist in j:
	#	print(f'{gist}: {j[gist]}')

	try:
		return(j['files'][f'{gist_filename}']['raw_url'])
	except KeyError:
		# Got: {'message': 'Bad credentials', 'documentation_url': 'https://docs.github.com/rest'}
		if j['message'] == 'Bad credentials':
			return ''
		else:
			print('uploadgist(): ', j, file=sys.stderr)
			raise

@app.route('/')
def homepage():
	return render_template('upload.html')

@app.route('/final/<file>')
def final(file):
	#return redirect(url_for('static', filename=file))
	return send_file(url_for('static', filename=file), mimetype='text/html', as_attachment=False, add_etags=False)


@app.route('/result/<csfile>')
def download_file(csfile):
	#flash(f'{csfile}')
	dotfile = csfile + '.dot'
	#if os.path.isfile(f"{UPLOAD_FOLDER}/{dotfile}") and os.path.getsize(f"{UPLOAD_FOLDER}/{dotfile}") > 0:
	#	return redirect(f"http://dreampuf.github.io/GraphvizOnline/?url=https://flurrywinde.pythonanywhere.com/uploads/{csfile}")
	# TODO: get java output for debugging
	status = os.system(f'java -cp {CSGV_FOLDER} Main "{UPLOAD_FOLDER}/{csfile}" > "{UPLOAD_FOLDER}/{dotfile}"')
	if status != 0:
		print(f'choicescript-graphviz returned {status}', file=sys.stderr)
		raise Exception("Couldn't parse scene file")
	return success(f"{UPLOAD_FOLDER}/{dotfile}")

def allowed_file(filename):
	return '.' in filename and \
		   filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# From: https://flask.palletsprojects.com/en/2.0.x/patterns/fileuploads/
# TODO: add stuff (e.g. security) from: https://blog.miguelgrinberg.com/post/handling-file-uploads-with-flask
@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
	if request.method == 'POST':
		# check if the post request has the file part
		if 'file' not in request.files:
			flash('No file part')
			return redirect(request.url)
		file = request.files['file']
		# If the user does not select a file, the browser submits an
		# empty file without a filename.
		if file.filename == '':
			#flash('No selected file')
			#return redirect(request.url)
			filename = "mygame-orig.txt"
			return redirect(url_for('download_file', csfile=filename))
		if file and allowed_file(file.filename):
			filename = secure_filename(file.filename)
			try:
				file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
			except FileNotFoundError:
				print(f'on server: {request.url_root}. Upload of {filename} failed.')
				raise
			return redirect(url_for('download_file', csfile=filename))
	#return redirect('https://flurrywinde.pythonanywhere.com/upload.html')
	return render_template('upload.html')
	#return '''
	#<!doctype html>
	#<title>Upload new File</title>
	#<h1>Upload new File</h1>
	#<form method=post enctype=multipart/form-data>
	#  <input type=file name=file>
	#  <input type=submit value=Upload>
	#</form>
	#'''

@app.route('/success/<dotcode>')
def success(dotcode):
	tree.readdot(dotcode)
	tree.allvars()
	tree.squash_goto()
	tree.squash_label()
	tree.showimportantvars3()
	tree.hideall()
	dotcode = tree.makedot()
	#tempfile.mkstemp(suffix=None, prefix=None, dir=None, text=False)
	#handle, filename = tempfile.mkstemp(dir='/home/  Flurrywinde  /mysite/output')
	#tree.cs2dot(filename)
	#newdot = os.path.basename(filename)

	# creating gist and getting url, script and clone link
	gisturl = uploadgist(dotcode)
	if gisturl:
		#return redirect(f"http://dreampuf.github.io/GraphvizOnline/?url=https://flurrywinde.pythonanywhere.com/output/{newdot}")
		return redirect(f"http://dreampuf.github.io/GraphvizOnline/?url={gisturl}")
	else:
		return render_template('choice_template.html', dotcode = dotcode)

# For old, unused method of submitting scene file via textarea. (templates/choice.html)
@app.route('/choice',methods = ['POST', 'GET'])
def login():
	if request.method == 'POST':
		os.system('echo post > post')
		dotcode = request.form['dotcode']
	else:
		os.system('echo get > get')
		dotcode = request.args.get('dotcode')
	return redirect(url_for('success',dotcode = dotcode))


@app.errorhandler(Exception)
def basic_error(e):
	if isinstance(e, HTTPException):
		httppassthru = False  # how handle http exceptions? Not passthru.
		if httppassthru:
			# pass through HTTP errors
			return e
		else:
			"""Return JSON instead of HTML for HTTP errors."""
			# start with the correct headers and status code from the error
			response = e.get_response()
			# replace the body with JSON
			response.data = json.dumps({
				"code": e.code,
				"name": e.name,
				"description": e.description,
			})
			response.content_type = "application/json"
			return response
	else:
		# All other exceptions for now
		# fetch some info about the user from the request object 
		user_ip = request.remote_addr 
		requested_path = request.path 
	 
		print("User with IP %s tried to access endpoint: %s" % (user_ip , requested_path), file=sys.stderr)
		print(e, file=sys.stderr)
		inspect(e, console=consolef)
		possible_causes = '\n<br>\n<br>Possible causes:\n<br>\n<br>'
		# TODO: not on-the-fly html
		if str(e) == 'maximum recursion depth exceeded':
			possible_causes += '\t* Infinite loop in your scene'
		elif isinstance(e, FileNotFoundError):
			possible_causes = '\n<br>\n<br>* File upload failure'
		else:
			possible_causes = ''
		return "An error occurred: " + str(e) + possible_causes

if __name__ == '__main__':
	app.run(debug = True)
