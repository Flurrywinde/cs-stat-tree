import os
import tempfile
from flask import Flask, redirect, url_for, request, render_template, flash
#from flask_cors import CORS
from werkzeug.utils import secure_filename
from cstree import CStree
import requests
import json

UPLOAD_FOLDER = '/home/Flurrywinde/uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'dot', 'gv'}

# The jinja2 template engine uses the following delimiters for escaping from HTML.

#	 {% ... %} for Statements
#	 {{ ... }} for Expressions to print to the template output
#	 {# ... #} for Comments not included in the template output
#	 # ... ## for Line Statements

# Run this to set up test web server at http://localhost:5000

# Then in browser, goto choice.html to send data to it

# Dependencies (besides cstree and ctree): flask, prompt_toolkit, networkx, pygraphviz, asteval, rich, flask_cors

app = Flask(__name__, static_url_path="", static_folder="static")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 1000 * 1000	# 1 meg. Raises RequestEntityTooLarge exception.
# Set the secret key to some random bytes. Keep this really secret! See: https://stackoverflow.com/questions/51436382/runtimeerror-the-session-is-unavailable-because-no-secret-key-was-set-set-the
app.secret_key = b'5_y#gL2"Fn\n48Qz\xec]/'
#CORS(app, resources={r"/*": {"origins": "*"}})

tree = CStree()

def uploadgist(dotcode):
	GITHUB_API="https://api.github.com"
	API_TOKEN='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'

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
		print(j)
		raise

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
	os.system(f'java -cp /home/Flurrywinde/choicescript-graphviz/ Main "{UPLOAD_FOLDER}/{csfile}" > "{UPLOAD_FOLDER}/{dotfile}"')
	return success(f"{UPLOAD_FOLDER}/{dotfile}")

def allowed_file(filename):
	return '.' in filename and \
		   filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# From: https://flask.palletsprojects.com/en/2.0.x/patterns/fileuploads/
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
			file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
			return redirect(url_for('download_file', csfile=filename))
	return redirect('https://flurrywinde.pythonanywhere.com/upload.html')
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
	#handle, filename = tempfile.mkstemp(dir='/home/Flurrywinde/mysite/output')
	#tree.cs2dot(filename)
	#newdot = os.path.basename(filename)

	# creating gist and getting url, script and clone link
	gisturl = uploadgist(dotcode)
	if gisturl:
		#return redirect(f"http://dreampuf.github.io/GraphvizOnline/?url=https://flurrywinde.pythonanywhere.com/output/{newdot}")
		return redirect(f"http://dreampuf.github.io/GraphvizOnline/?url={gisturl}")
	else:
		return render_template('choice_template.html', dotcode = dotcode)

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
    return "an error occured: " + str(e)

if __name__ == '__main__':
	app.run(debug = True)
