#!/usr/bin/python

# whatis: Class CStree contains a list of CSnode's (which extend class Ctree to add visual traversal capabilities using prompt_toolkit) corresponding to a choicescript game's tree.
# Dependency: pygraphviz to read in .dot files. Access it with `pgv`.
# New properties: cur (current node (will be highlighted)), maxid
# New methods: 

import os
import sys
import enum
import copy
import re
import signal
import subprocess
import shlex
import time
from itertools import product
from itertools import cycle
import asyncio

from ctree import Ctree

from configparser import ConfigParser
#import asteval
from asteval import Interpreter

import pygraphviz as pgv  # See: https://pygraphviz.github.io/documentation/stable/tutorial.html
# PyGraphviz AGraph reference: https://pygraphviz.github.io/documentation/stable/reference/agraph.html
import networkx as nx

from rich import inspect
from rich import print
from rich.console import Group
from rich.console import Console
from rich.highlighter import Highlighter
from rich.color import Color
from rich.table import Table
from rich import box
from rich.style import Style
from rich.text import Text

from prompt_toolkit import prompt
from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.input import create_input
from prompt_toolkit.keys import Keys

console = Console()
consolef = Console(stderr=True)
safeeval = Interpreter()
sess = PromptSession()

def debug_pedge(node):
	if hasattr(node, 'parent_edge_label'):
		print(f' \[pedge: {node.parent_edge_label}] ', end='')
		prompt()
	else:
		print(f' \[no pedge] ', end='')

def signal_handler(sig, frame):
    print('You pressed Ctrl+C!')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# return string without Rich-style bbcode markup
def nostyle(styledtext):
	return str(Text.from_markup(styledtext))

# split a *command into its constituent parts (cmd, varname, varvalue (list of space-delimited tokens, and valuestr is it in string form) and return them
def csexpr(cscode):
	# TODO: hmm, current code uses this for both *if and *set, but for *if it's "wrong" in that an *if doesn't have a varname, but ok for now, as code will work fine in all cases, I'm pretty sure. Should change this to be cmd and cmdparms
	cscode = re.sub(r'%[+-]', r' \g<0> ', cscode)  # add spaces around fairmaths
	cscode = re.sub(r'([^%])[+-/*]', r' \g<0> ', cscode)  # add spaces around all operators except fairmaths
	tokens = cscode.split()
	try:
		cmd = tokens[0]
	except IndexError:
		return None
	try:
		varname = tokens[1]
	except IndexError:
		# e.g. START won't have index 1
		varname = None
	try:
		varvalue = tokens[2:]
		valuestr = ' '.join(varvalue)
	except IndexError:
		varvalue = None
		valuestr = None
	return (cmd, varname, varvalue, valuestr)

def seteval(cscode, curvars):
	curvars = curvars.copy()
	# TODO: check if cscode even uses the var, but for now, just set them all
	#for perm in allperms(curvars):
	for varname, varvals in curvars.items():
		#print(f"\tvar: {varname} = {varvals}")
		for path, val in varvals.items():
			#print(f"\t set {varname} = {val}")
			safeeval(f'{varname} = {val}')
	cmd, varname, varvalue, valuestr = csexpr(cscode)
	#if cmd == 'CREATE' or cmd == 'TEMP':	  # no need to even proc these at all
	#	safeeval(f'{varname} = {varvalue}')
	#	#print(safeeval.symtable[varname])
	#elif cmd == 'SET':
	if varvalue[0] in ['+', '-', '*', '/', '%']:
		varvalue = f'{varname} {valuestr}'	# need add varname if operator first, cuz choicescript
	else:
		varvalue = valuestr
	#safeeval(f'{varname} = {varvalue}')
	result = safeeval(f'{varvalue}')
	try:
		result = int(result)
	except TypeError:
		# if not an int (was None)
		pass
	except ValueError:
		# if not an int-able (was a str)
		pass
	#print(f'*set {varname} {varvalue} = {result}')
	return result, f' -> {varvalue} = {result}'

def ifeval(cscode, curvars):
	def allperms(d):
		# From: https://stackoverflow.com/questions/15211568/combine-python-dictionary-permutations-into-list-of-dictionaries
		# delme = oh wait, didn't work (but thought it had to work on the node.vars, not curvars, which has only one value each var, geez)
		return [dict(zip(d, v)) for v in product(*d.values())]

	curvars = curvars.copy()
	cscode = re.sub(r'IF', '', cscode)
	cscode = re.sub(r'=', '==', cscode)  # TODO: check for if already is == ? Maybe unnecessary?
	#print(f"ifeval'ing: {cscode}")
	# TODO: check if cscode even uses the var, but for now, just set them all
	#for perm in allperms(curvars):
	for varname, varvals in curvars.items():
		#print(f"\tvar: {varname} = {varvals}")
		for path, val in varvals.items():
			#print(f"\t set {varname} = {val}")
			safeeval(f'{varname} = {val}')
	# now all vars set, so check the cond
	ret = safeeval(cscode.strip())
	#print(f"result: {cscode} -> {ret}")
	#prompt('k')
	return ret

class Type(enum.IntEnum):
	start = 0; end = -1; text = 7; choice = 1; var = 3; label = 4; cond = 5; goto = 6
	# non-dot Type's
	option = 2  # there are no "option"s in the .dot file (it's on the edge instead)
	loopgoto = 8
	multigoto = 9
	closenode = 10  # a ... node when "closed", i.e. whole branch eaten
	hidenode = 11  # a ... node when just individual nodes "hidden" inside

# Fun color theory: https://johnthemathguy.blogspot.com/

vardark = [
		# darks
		'dark_red',		# rgb(135,0,0)
		'orange4',		# rgb(135,95,0)
		#'yellow3',		 # rgb(215,215,0)  # can't read it
		'dark_green',	# rgb(0,95,0)
		'dark_blue',	# rgb(0,0,135)
		'purple4',		# rgb(95,0,175)
		'deep_pink3'   # rgb(215,0,135)
		]
varlight = [
		# lights
		'red3',			# rgb(215,0,0)
		'orange3',		# rgb(215,135,0)
		'yellow2',		# rgb(215,255,0)
		'light_green',	# rgb(135,255,135)
		'sky_blue1',	# rgb(135,215,255)
		'medium_purple3',  # rgb(135,95,215)
		'pink1'		   # rgb(255,175,215)
		]

#class SelectedText(Highlighter):
#	def highlight(self, text):
#		#text.stylize('color(111)')
#		text.stylize('r')  # reverse

# Applying a highlighter
#selectText = SelectedText()

# New way to highlight
def selectText(text):
	return f'[r]{text}'

def getnodetype(dotnode):
	# TODO: make these configurable, but for now, since choicescript-graphviz will consistently use a certain shape for each type, this is fine
	shape = dotnode.attr['shape']
	if shape == 'box':
		return Type.text
	elif shape == 'point':
		return Type.goto
	elif shape == 'cds':
		return Type.label
	elif shape == 'triangle':
		return Type.choice
	elif shape == 'hexagon':
		return Type.var
	elif shape == 'diamond':
		return Type.cond
	elif shape == 'doublecircle':
		if dotnode.attr['startln'] == '0':
			return Type.start
		if dotnode.attr['startln'] == '-1':
			return Type.end
	# non-graphviz node types
	try:
		gototype = dotnode.attr['loopgoto']
	except IndexError:
		consolef.print('non-graphviz node has no loopgoto either')
		sys.exit(1)
	if gototype == 0:  # false
		return Type.loopgoto
	else:
		# assume it's a multigoto
		return Type.multigoto
	# TODO: throw error?
	consolef.print('cannot determine node type')
	sys.exit(1)
	return None

def colorgoto(dot, id):
# takes a dot id, gets its label and gives it a color. 03/16/22-now, it's label and line num, or just line num if no label
	nodetype = getnodetype(dot.get_node(id))
	startln = dot.get_node(id).attr['startln']
	label = dot.get_node(id).attr['label']
	if int(id) <= 1:
		# special cases: 0 for start, 1 for end
		return '[red]' + label
	elif nodetype == Type.label:
		goto =  f'[plum4]{label} [yellow2]({startln})'
	else:
		goto = f'[yellow2]{startln}'
	return goto

def colorlabel(startln, type, plainlabel):
# add color to label (used both during init and later, so doesn't count on csnode properties)
	#print(f'{startln}: {plainlabel}')
	if startln == '':
		# some nodes have no startln, e.g. new nodes created by remove_cycles and singleparent (?)
		return plainlabel
	if int(startln) >= 0:
		clabel = f'[bold yellow]{startln}: [not bold]'
	else:
		clabel = ''  # START and END
	if type == Type.text:
		# text blocks get the tooltip
		clabel += f'[not bold][grey46]{plainlabel}'
	elif type == Type.goto:
		if int(startln) >= 0:
			clabel = f'[red]{plainlabel} [grey27](line {startln})'  # TODO: if next node is a goto, this startln is redundant
		else:
			clabel = f'[red]{plainlabel}'
			print('nlg')  # seems imp also
			raise
	elif type == Type.label:
		clabel += f'[plum3]{plainlabel}'
	elif type == Type.choice:
		if int(startln) >= 0:
			clabel = f'[red]{plainlabel} [grey27](line {startln})'
		else:
			print('imp?')
			raise
	elif type == Type.option:
		clabel += f'[orange3]{plainlabel}'
	elif type == Type.var:
		clabel += f'[white]{plainlabel}'
	elif type == Type.cond:
		clabel += f'[white]{plainlabel}'
	elif type == Type.start:
		clabel = f'[red]{plainlabel}'  # get rid of startln:
	elif type == Type.end:
		clabel = f'[red]{plainlabel}'  # get rid of startln:
	else:
		clabel += f'[white]{plainlabel}'

	#print(f'{clabel}, {startln}, {type}')
	#print(f'------------------')
	return clabel

class CSnode(Ctree):
	# cur: Tree2  # Doesn't work (but way around?). See: https://stackoverflow.com/questions/2035423/how-to-refer-to-the-class-from-within-it-like-a-recursive-function#:~:text=In%20Python%20you%20cannot%20reference,you%20are%20trying%20to%20achieve.

	def __init__(
		self,
		dotnode,
		mastertree,
		*,
		style = "tree",
		guide_style = "tree.line",
		expanded: bool = True,
		highlight: bool = False,
		hide_root: bool = False,
	) -> None:
		try:
			dotnode.attr
		except AttributeError:
			# id can also be just '1', not a dotnode
			if type(dotnode) is int:
				dotnode = str(dotnode)
			elif type(dotnode) is not str:
				print(f'Trying to init a CSnode with id of {dotnode}')
				sys.exit(1)
		if type(dotnode) is not str:
			nodetype = getnodetype(dotnode)
			label = self.initlabel(dotnode, nodetype)
		else:
			# TODO: this else is (so far) for when making a new CSnode for ... nodes, so maybe make a new Type for this (phantom goto nodes are still in dot, so this wasn't necessary until now)
			nodetype = None
			label = ''
		Ctree.__init__(self, label=label, style=style, guide_style=guide_style, expanded=expanded, highlight=highlight, hide_root=hide_root)
		#super().__init__()  # equivalent?
		self.tree = mastertree
		self.type = nodetype
		if hasattr(dotnode, 'attr'):
			self.startln = dotnode.attr['startln']
		else:
			# The ... node case again (sigh)
			self.startln = -2
		self.plainlabel = label
		self.label = colorlabel(self.startln, nodetype, self.plainlabel)
		self.truelabel = self.label
		self.id = dotnode
		self.next = None
		self.prev = None
		self.parent = None
		self.closed = False
		self.squasheds = []
		self.vars = {}
		if hasattr(dotnode, 'attr'):
			oldgoto = dotnode.attr['oldgoto']
			if oldgoto:
				self.oldgoto = oldgoto
		self.otherparents_str = ''
		self.otherparents = []
		if hasattr(dotnode, 'attr'):
			otherparents = dotnode.attr['otherparents']
			if otherparents:
				self.otherparents_str = otherparents
				self.otherparents = otherparents

	def gonext(self):
		cursrch = self.tree.cur
		# Remove selectedness from current node
		#CStree.cur.label = CStree.cur.plainlabel
		cursrch.notcur()
		ocur = cursrch
		# Find where to go
		while cursrch.parent is not None:
			if cursrch.next is not None:
				#CStree.cur.next.label = selectText(CStree.cur.next.label)
				cursrch.next.makecur()
				return self.tree.cur  # this is changed in makecur()
			else:
				# Try parent's next, i.e. parent's next sibling, i.e. uncle
				cursrch = cursrch.parent
				#print(cursrch)
				#time.sleep(1)
		# Reached root node, so no next found
		#ocur.makecur()
		#return None
		# Instead of failing, try gochildren()
		if self.children:  # this if should prevent infinite loop in case where gonext calls gochildren calls gonext again (maybe node with neither children nor next, i.e. a "tree" of just one node)
			return self.gochildren()
		else:
			ocur.makecur()
			return None

	def goprev(self):
		if self.tree.cur.prev is not None:
			self.tree.cur.notcur()
			self.tree.cur.prev.makecur()
			return self.tree.cur
		else:
			#return None
			# Instead of failing, try goparent()
			if self.parent:
				return self.goparent()
			else:
				return None

#	def gochildren(self):  # experimenting to find out how to handle groups
#		if len(CStree.cur.children) > 0:
#			CStree.cur.label = CStree.cur.plainlabel
#			try:
#				CStree.cur.children[0].label = selectText(CStree.cur.children[0].label)
#			except TypeError:
#				# str or Text instance required, not {text!r}
#				inspect(CStree.cur.children[0])
#				inspect(CStree.cur.children[0].label)
#				#print(type(CStree.cur.children[0].label))	# Huh? Not renderable error
#				#print(CStree.cur.children[0].label.__class__)	# as above
#				# print(f'Len is {len(list(CStree.cur.children[0].label))}')  # no len, not iterable
#				if isinstance(CStree.cur.children[0].label, Group):
#					inspect(CStree.cur.children[0].label.renderables)
#					inspect(CStree.cur.children[0].label.renderables[0])
#			CStree.cur = CStree.cur.children[0]
#			return CStree.cur
#		else:
#			return None

	def gochildren(self):
		if len(self.tree.cur.children) > 0:
			# If closed, open it first
			#if self.tree.cur.children[0].label == '...':
			if self.tree.cur.children[0].type in [Type.closenode, Type.hidenode]:
				self.tree.cur.openclose()
			# Go to child
			self.tree.cur.notcur()
			try:
				self.tree.cur.children[0].makecur()
			except AttributeError:
				# was a Ctree?!?
				#inspect(self.tree.cur.children[0])  # not showing up cuz TUI
				#print(self.tree.cur.children[0])
				#print('argh!!! These outputs no show. How make show? Or save inspect to file?')
#				with open("report.txt", "wt") as report_file:
#					consolef = Console(file=report_file)
#					consolef.rule(f"Report Generated {datetime.now().ctime()}")
#					inspect(self.tree.cur.children[0], console=consolef)
				consolef.rule(f"Report Generated datetime.now().ctime()")
				inspect(self.tree.cur, console=consolef)
				inspect(self.tree.cur.children, console=consolef)
				inspect(self.tree.cur.children[0], console=consolef)
				sys.exit(2)
			return self.tree.cur
		else:
			# No children
			#return None  # instead of do nothing, try gonext:
			return self.gonext()

	def goparent(self):
		if self.tree.cur.parent is not None:
			self.tree.cur.notcur()
			self.tree.cur.parent.makecur()
			return self.tree.cur
		else:
			return None

	def add(
		self,
		dotnode,
		*,
		style = None,
		guide_style = None,
		expanded: bool = True,
		highlight: bool = False,
	) -> "CSnode":
		# Make new node
		node = CSnode(
			dotnode,
			self.tree,
			style=self.style if style is None else style,
			guide_style=self.guide_style if guide_style is None else guide_style,
			expanded=expanded,
			highlight=self.highlight if highlight is None else highlight,
		)
		# Give new node current node as parent
		node.parent = self
		# Put newborn at end of list, so previous youngest becomes its prev, previous youngest's next becomes newborn
		if len(self.children) > 0:
			node.prev = self.children[-1]
			self.children[-1].next = node
		self.children.append(node)
		# return it
		return node

	def initlabel(self, dotnode, type):
		if dotnode.attr['startln']:
			startln = dotnode.attr['startln']
		else:
			# remove_cycles and/or singleparent create new nodes with no startln (only label)
			startln = -1
		if dotnode.attr['shape'] == 'box':
			# text blocks should always have a tooltip; use it instead of choicescript-graphviz's original label (e.g. T[1]). Assume shape box is a text block
			label = dotnode.attr["tooltip"]
		else:
			label = dotnode.attr['label']
		# plainlabel and truelabel
		# Not possible for label to be a Group already? I think not, so no need to account for it here.
		#if isinstance(label, Group):
		#	if len(label.renderables) > 0:
		#		self.plainlabel = label.renderables[0]
		#		self.truelabel = label.renderables[0]
		#	else:
		#		self.plainlabel = ''
		#		self.truelabel = ''
		#else:
		#	self.plainlabel = label
		#	self.truelabel = label
		# (colorized) label (prefixed by startln:)
		return label

	def constructlabel(self):
	# csnode already made but might need label reconstructed, like if squasheds changed
	# Hmm, maybe don't need this (yet). See squashedlabel() below
		self.label = colorlabel(self.startln, self.type, self.plainlabel)
		for i in self.squasheds:
			#self.label_append(
			pass

	def label_prepend(self, labelchild):
		if not isinstance(self.label, Group):
			# not already a group
			# turn into a group (unless label == '')
			if self.label != '':
				self.label = Group(
						labelchild,
						self.label
						)
			else:
				self.label = labelchild
		else:
			if self.label.renderables[0] == '':
				self.label.renderables[0] = labelchild
			else:
				self.label.renderables.insert(0, labelchild)

	def label_append(self, labelchild):
		if not isinstance(self.label, Group):
			# not already a group
			# turn into a group (unless label == '')
			if self.label != '':
				self.label = Group(
					self.label,
					labelchild
					)
			else:
				self.label = labelchild
		else:
			if self.label.renderables[0] == '':
				self.label.renderables[0] = labelchild
			else:
				self.label.renderables.append(labelchild)

	# Children of node become children of parent. (Remove node done elsewhere.)
	def squash(self):
		# after the two nodes squashed together, call this to combine their labels in the right way (so far, does nothing except for Type.text where it merges with parent (which will always be a *label since squash_label() only calls squash() in this case)
		def squashedlabel(self):
			# Child's label might append (linewise or blockwise) to parent's, depending on type
			if self.type == Type.goto:
				# goto label disappears (but might be 2nd thing in a Group)
				pass
				#inspect(self)
				#inspect(self.label)
				#prompt()
			elif self.type == Type.choice:
				# choice label disappears
				# self.parent.label_append(self.label)	# if want to keep
				pass
			elif self.type == Type.text:
				# label merges with what follows, but only if it's a text
				# IOW, text block merges upward into its label
				# can assume parent is a label, as squash_label() only calls this if it is
				#print('s-sl-t')
				#print(f'{self.parent.label}')
				#print(f'{self.label}')
				#a = prompt('before')
				try:
					self.parent.label = '[bold plum3]' + self.parent.plainlabel + ': [not bold][grey46]' + self.plainlabel	# stopped working because now sometimes the label was a Group
				except TypeError:
					if isinstance(self.parent.label, Group):
						self.parent.label_append('[grey46]' + self.plainlabel)
				#print(f'{self.parent.label}')
				#print(f'{self.label}')
				#inspect(self)
				#inspect(self.parent)
				#prompt('after')
			else:
				print('should never happen')
				raise
			# from previous version: (del?)
			# v.parent.tooltip += v.tooltip  # += just in case already had, but... ever happen?
			# v.parent.plainlabel += v.parent.tooltip

		if len(self.parent.children) == 1:
			# node is only child
			self.parent.children = self.children
		else:
			# parent has multiple children, so must find right place to put new children
			idx = self.parent.children.index(self)
			if idx == 0:
				before = []
				after = self.parent.children[1:]
			else:
				before = self.parent.children[0:idx]
				try:
					after = self.parent.children[idx+1:]
				except IndexError:
					# I think it's safe to assume this (i.e. no more)
					after = []
			self.parent.children = before + self.children + after
		# Assign new parent to all node's children
		for i in self.children:
			i.parent = self.parent
		# Put node in parent's squasheds
		self.parent.squasheds.append(self)
		# Add node's label to parent's label
		squashedlabel(self)

	# Format node's vars and append to its label (all one line if perline is False, if nolabel is false, return it instead)
	def showvars(self, showvars=None, short=False, perline=False, nolabel=False):
		def showvars_short():
			tablevars = {}
			# Make: { 'varname': [1, 2, 2], ... }
			for var, paths in self.vars.items():
				if var in showvars:
					for path, val in paths.copy().items():
						if var in tablevars.keys():
							tablevars[var].append(str(val))
						else:
							# not in tablevars yet
							tablevars[var] = [str(val)]
			# tablevars2: { 'varname': '1, 2', ... }
			tablevars2 = {}
			for var, vals in tablevars.items():
				# removed dupes
				vals = list(dict.fromkeys(vals))
				tablevars2[var] = ','.join(vals)
			# append vars to label if there are any
			if len(tablevars2) > 0:
				# iterate tablevars2 to construct ret (string of vars with all possible values, comma-separated list)
				#ret = '[black on yellow]'
				ret = ''
				for var, vals in tablevars2.items():
					color = self.tree.varcolors[var]
					ret += f"[white on {color}]{var}[{self.tree.config.get('default colors', 'equals')} on default] = [{self.tree.config.get('default colors', 'varvalue')}]{vals} "
					if perline:
						ret += '\n'
				# remove final \n
				ret = ret[0:-1]
				if nolabel:
					return ret
				else:
					self.label_append(ret)
		# End sub-function showvars_short()

		def showvars_long():
			tablevars = []
			# tablevars: [[1.2, str, 17], [1.2.7, str, 18], [1.2, int, 7], ... ]
			for var, paths in self.vars.items():
				if var in showvars:
					for path, val in paths.copy().items():
						tablevars.append([path, var, str(val)])
			tablevars.sort(key=lambda x: sum(map(int, x[0].split('.'))))
			curpath = ''
			row = ''
			for path in tablevars:
				color = self.tree.varcolors[path[1]]
				if path[0] != curpath:
					# new path, so show path
					if not row:
						# new row, so make row
						color = self.tree.varcolors[path[1]]
						row = f"[{self.tree.config.get('default colors', 'path')}]{path[0]}: [white on {color}]{path[1]}[{self.tree.config.get('default colors', 'equals')} on default]=[{self.tree.config.get('default colors', 'varvalue')}]{path[2]} "
					else:
						# append another path to row (\n if perline)
						if perline:
							row += '\n'
						row += f"[{self.tree.config.get('default colors', 'path')}]{path[0]}: [white on {color}]{path[1]}[{self.tree.config.get('default colors', 'equals')} on default]=[{self.tree.config.get('default colors', 'varvalue')}]{path[2]} "
				else:
					# not a new path, append to row without path marker
					row += f"[white on {color}]{path[1]}[{self.tree.config.get('default colors', 'equals')} on default]=[{self.tree.config.get('default colors', 'varvalue')}]{path[2]} "
				#print(f'setting curpath:	"{curpath}" = path0: "{path[0]}"')
				curpath = path[0]
				#print(f'is it set? curpath: "{curpath}" = path0: "{path[0]}"')
			# last one
			if row:
				#print('writing row')
				if nolabel:
					#consolef.print(f'nolabel so returning: {row}')
					return row
				else:
					self.label_append(row)
		# End sub-function showvars_long()
	# Begin showvars() proper:
		# showvars == None means all. Otherwise only the ones in showvars (list)
		if showvars is None:
			showvars = self.tree.allvarnames
		# show vars
		if short:
			# Short form: var = 1,2
			return showvars_short()
		else:
			return showvars_long()

	# Format node's vars and append to its label (one path per line (all vars on each line, e.g. 1.2: hp=9str=17, then another line just like this but for another path, colors still don't use self.varcolors[], should sort vars)
	def showvars_perline(self):
		tablevars = []
		colorcycle = cycle(vardark)
		for var, paths in self.vars.items():
			for path, val in paths.copy().items():
				tablevars.append([path, var, str(val)])
		tablevars.sort()
		curpath = ''
		row = ''
		for path in tablevars:
			path = path.copy()
			print(f'cp: "{curpath}" - "{path[0]}", {path[1]}, {path[2]}')
			#prompt()
			if path[0] != curpath:
				if row:
					print('writing row')
					self.label_append(row)
				print('new row')
				row = f'{path[0]}: [on {next(colorcycle)}]{path[1]}={path[2]}'
			else:
				print('append to row')
				row += f'[on {next(colorcycle)}]{path[1]}={path[2]}'
			print(f'setting curpath:	"{curpath}" = path0: "{path[0]}"')
			curpath = path[0]
			print(f'is it set? curpath: "{curpath}" = path0: "{path[0]}"')
		# last one
		if row:
			print('writing last row')
			self.label_append(row)

	def append2toplabel(self, toappend):
		if isinstance(self.label, Group):
			self.label.renderables[0] += toappend
		else:
			self.label += toappend

	def makecur(self):
		self.tree.cur = self
		if not isinstance(self.label, Group):
			self.truelabel = self.label
			self.label = selectText(self.label)
		else:
			# Label is a group
			if len(self.label.renderables) > 0:
				self.truelabel = self.label.renderables[0]
				self.label.renderables[0] = selectText(self.label.renderables[0])

	def notcur(self):
		# Note: notcur() doesn't touch CStree's cur. Should it check?
		if not isinstance(self.label, Group):
			self.label = self.truelabel
		else:
			# Label is a group
			if len(self.label.renderables) > 0:
				self.label.renderables[0] = self.truelabel

	# Put hidden node's label into csnode attribute hidden
	def addhidden(self, swallowed, prepend=True):
		# debugging note: checked swallowed for parent_edge_label here, always had, but sometimes '', other times was what shows in xdot, but Y's did not
		if not hasattr(self, 'hiddens'):
			self.hiddens = []
		print(f'before: on [{self.startln}]')
		inspect(self.hiddens)
		inspect(swallowed.label)
		if not isinstance(swallowed.label, Group):
			print(f'swallow {swallowed.label} not a group. Hiding: {nostyle(swallowed.label)}')
			if prepend:
				self.hiddens = [nostyle(swallowed.label)] + self.hiddens
			else:
				self.hiddens.append(nostyle(swallowed.label))
		else:
			print(f'swallow is a group')
			if not prepend:
				ret = self.hiddens
			else:
				ret = []
			print(f'ret set to {ret}')
			for hidden in swallowed.label.renderables:
				ret.append(nostyle(hidden))
			print(f'now ret is {ret}')
			if prepend:
				ret.extend(self.hiddens)
			self.hiddens = ret
		print('after')
		#inspect(self.hiddens)
		#if int(swallowed.startln) in [4, 15, 19, 24, 35, 37, 48, 51, 56]:
		#	prompt()
		#else:
		#	print(f'on {self.id}')
		#	#inspect(self)  # self is the ... node (so self.startln is always -2)
		#	inspect(swallowed)
		#	prompt()

	# Hides the node, i.e. replaces it with ... (intended to hide multiple nodes after it too)
	# Returns the new ... node
	# This doesn't use truechildren (problem?), but the ... node will have node's children (this seems sufficient differentiation, even if node has no children because then go by lack of truechildren)
	def hide(self, updatecur=True):
		# can call this on a ... or next to it above or below
		if not self.parent:
			consolef.rule(f'HIDE: {self.plainlabel} - ' + str(subprocess.check_output(shlex.split('date +%I:%M'))) + ' - Cannot hide STARTing node')
			return
		consolef.rule(f'HIDE: {self.plainlabel} - ' + str(subprocess.check_output(shlex.split('date +%I:%M'))))
		consolef.print(f'parent\'s label = {self.parent.plainlabel} / {self.parent.label}')
		if self.parent is not None and self.parent.type == Type.hidenode:
			consolef.print('Parent is a ... case')  # assumes parent of Type.closenode is impossible
			# parent is hidden [s]parent is closed or hidden...[/s] no wait, closed ... by definition has no children (and could go by plainlabel for this (impossible) case)
			if len(self.parent.children) == 1:
				self.parent.addhidden(self)
				self.parent.children = self.children
				# TODO: trueself stuff here
				if updatecur:
					self.notcur()
				if self.children:
					if updatecur:
						self.children[0].makecur()
					self.children[0].parent = self.parent
				elif updatecur:
					# Usually child becomes cur, but if no child, parent
					self.parent.makecur()
			else:
				consolef.print(f'Parent cannot have multiple children')
			# TODO: what about next/prev?
		elif self.children and len(self.children) == 1 and self.children[0].type == Type.hidenode:
			consolef.print(f'child is a ... case: {self.children[0].plainlabel} / {self.children[0].label}')
			self.children[0].addhidden(self)
			# if there's a pedge, copy it over (TODO: what do if already had a pedge?)
			if hasattr(self, 'parent_edge_label'):
				if hasattr(self.children[0], 'parent_edge_label'):
					print('already has pedge')
					sys.exit(1)
				else:
					self.children[0].parent_edge_label = self.parent_edge_label
			# make self into a ... node and consume ... aspects of child (or move the ... child to self after modifying it?)
			if len(self.parent.children) == 1:
				self.parent.children = self.children
			elif len(self.parent.children) > 1:
				try:
					idx = self.parent.children.index(self)
				except ValueError:
					consolef.rule('should never happen: not in own parent\'s children')
					# hit hide() twice, said not in list
					inspect(self, console=consolef)
					inspect(self.parent, console=consolef)
					inspect(self.parent.children, console=consolef)
					sys.exit(1)
				self.parent.children[idx] = self.children[0]
			else:
				consolef.print('Impossible')
			# update next/prev
			if self.next:
				self.children[0].next = self.next
				self.next.prev = self.children[0]
			if self.prev:
				self.children[0].prev = self.prev
				self.prev.next = self.children[0]

			self.children[0].parent = self.parent
			if updatecur:
				self.notcur()
				self.children[0].makecur()
			# TODO: trueself stuff here
		elif self.type == Type.hidenode:
			consolef.print(f'self case: {self.plainlabel} / {self.label}')
			# self is already a ... node, so consume child, if any
			if len(self.children) == 1:
				self.addhidden(self)
				self.trueself = self.children[0]  # old trueself gone ok? Or should append to list?
				self.children[0].parent = self
				self.children = self.children[0].children
			else:
				consolef.print(f"can't hide: no children or multiple children")
				# TODO: no children case maybe hide upwards
			# TODO: what about next/prev?
		elif len(self.children) > 1:
			# Prevent multiple children from being slurped up
			pass
		else:
			# No ...'s anywhere, so turn self into a ... and hide child inside
			consolef.print(f'no ... (new node) self case: {self.plainlabel} / {self.label}')
			#nodots = True
			hidedots = self.tree.newnode('...')
			hidedots.type = Type.hidenode
			hidedots.trueself = self
			hidedots.parent = self.parent
			# hidedots.addhidden(self)  # wrong order when here (came after the below addhidden call???)
			#hidedots.label += '[r]'  # why did I put this??? I think meant makecur()

			# if there's a pedge, copy it over (TODO: what do if already had a pedge?)
			# TODO: need to also check pedge for other node involved?
			if hasattr(self, 'parent_edge_label'):
				hidedots.parent_edge_label = self.parent_edge_label

			# if self has children
			if self.children:
				# put self's child into self (so grandchildren are now self's child)
				try:
					# give new node old node's child's children
					hidedots.children = self.children[0].children
				except IndexError:
					consolef.rule('[0] no good')
					inspect(self, console=consolef)
					inspect(self.parent, console=consolef)
					inspect(self.parent.children, console=consolef)
					sys.exit(1)
				# give new ... node its hiddens property (children[0] known to exist at this point)
				hidedots.addhidden(self.children[0])
				try:
					# make new parentage bidirectional
					self.children[0].parent = hidedots
				except:
					consolef.rule('could not make child\'s parent into hidedots')
					raise
				# Update child's child's parent
				if self.children[0].children:
					self.children[0].children[0].parent = hidedots
			else:
				# No ...'s yet and no children = can't close
				return

			# add self to hiddens
			hidedots.addhidden(self)

			# Now make self's parent point to the new ... node
			try:
				idx = self.parent.children.index(self)
			except ValueError:
				consolef.rule('# hit hide() twice, said not in list')
				# hit hide() twice, said not in list
				inspect(self, console=consolef)
				inspect(self.parent, console=consolef)
				inspect(self.parent.children, console=consolef)
				sys.exit(1)
			self.parent.children[idx] = hidedots  # removes self? Should.

			# update hidedots next/prev
			if len(hidedots.parent.children) > 1:
				if self.next:
					hidedots.next = self.next
					self.next.prev = hidedots
				if self.prev:
					hidedots.prev = self.prev
					self.prev.next = hidedots

			# make new ... node the current node
			if updatecur:
				self.notcur()
				hidedots.makecur()

	# close node means children replaced by a ... node, so in other words all branches below get hidden
	# sets node's closed to True and truechildren to what children was
	def openclose(self):
		if self.children is None or len(self.children) == 0:
			# Can't open or close if no children
			return
		# Has at least 1 child
		if self.closed:
			# Open it
			self.closed = False
			self.children = self.truechildren
			self.truechildren = None
		else:
			# Close it
			self.closed = True
			self.truechildren = self.children
			closedots = self.tree.newnode('...')
			closedots.type = Type.closenode
			closedots.parent = self
			self.children = [closedots]

# End of class CSnode(Ctree)

class CStree():
	def __init__(self, configfile=None):
		def mkdir_p(path):
			try:
				os.makedirs(path)
			except OSError as exc:	# Python >2.5
				if exc.errno == errno.EEXIST and os.path.isdir(path):
					pass
				else:
					raise

		self.cur: CSnode = None
		self.maxid = '0'
		self.dot_orig: pgv.AGraph
		self.dot_acyclic: pgv.AGraph
		# self.nodes: CSnode  # list of them, so...
		self.nodes = {}
		self.allvarnames = []
		self.colorcycle = cycle(vardark + varlight)
		self.varcolors = {}
		self.config = ConfigParser()

		if configfile is None:
			userhome = os.path.expanduser('~')
			configfolder = userhome + '/.config/cstree'  # do this the right way, not str catting lol
			configfile = configfolder + '/config.ini'
		self.getconfig(self.config, configfile)

	def getconfig(self, config, configfile):
		# Make default config file if it doesn't exist yet
		if not os.path.exists(configfile):
			# Sections
			config.add_section('main')
			config.add_section('node properties')
			config.add_section('default colors')
			# Config items
			config.set('main', 'selected', 'reverse')
			config.set('main', 'default_squasheds', 'goto, label, text, choice, option')      # squashed means could be visible but becomes part of parent node
			config.set('main', 'hidden commands', 'comment, page_break, line_break')  # hidden means not visible
			config.set('node properties', 'goto.squashed', 'hidden')
			config.set('node properties', 'label.squashed', 'inline')
			config.set('node properties', 'label.suffix', '": "')
			config.set('node properties', 'text.squashed', 'block')
			config.set('node properties', 'text.color', 'grey46')
			config.set('node properties', 'choice.squashed', 'no')
			config.set('node properties', 'option.squashed', 'block')
			config.set('default colors', 'guide_style', 'blue')
			config.set('default colors', 'linenum', 'bold yellow')
			config.set('default colors', 'choice', 'red')
			config.set('default colors', 'option', 'orange3')
			config.set('default colors', 'label', 'bold plum3')
			config.set('default colors', 'gototarget', 'plum4')
			config.set('default colors', 'text', 'white')
			config.set('default colors', 'goto', 'white')
			config.set('default colors', 'varcmd', 'white')
			config.set('default colors', 'varname', 'green')
			config.set('default colors', 'varvalue', 'grey46')
			config.set('default colors', 'cond', 'magenta')
			with open(configfile, 'w') as f:
				config.write(f)
		else:
			config.read(configfile)
			#inspect(config.get('colors', 'varname'))  # can also use .getint and .getfloat
			#inspect(config.get('main', 'hidden commands'))  # spaces ok, it seems
			#sys.exit()

	def nextid(self):
		# Sets maxid to maxid + 1 and returns it
		self.maxid = str(int(self.maxid) + 1)
		return self.maxid

	def remove_cycles(self, dot):
		def remove_cycle(dot, G):
			try:
				C = nx.find_cycle(G, '0')
			except nx.NetworkXNoCycle:
				return False
			#for n in C:
			#	print(f'{dot.get_node(n[0]).attr["label"]}({n[0]}) -> {dot.get_node(n[1]).attr["label"]}({n[1]})')
			n = C[-1]  # Assume last node is the node that goes back to the first node
			predstartln = dot.get_node(n[0]).attr['startln']
			dot.remove_edge(n[0], n[1])
			maxid = sorted(G.nodes, key=int)[-1]
			nextid = str(int(maxid)+1)
			#dot.add_node(nextid, label=f'(cycle) Goto node {n[1]}')
			startln = dot.get_node(n[1]).attr['startln']
			targetlabel = colorgoto(dot, n[1])
			dot.add_node(nextid, label=f'(cycle) [bold yellow]{predstartln}: [not bold white]Goto {targetlabel}')
			dot.get_node(nextid).attr['oldgoto'] = startln
			dot.get_node(nextid).attr['loopgoto'] = 1  # true
			dot.add_edge(n[0], nextid)
			return True

		c = 0
		G = nx.nx_agraph.from_agraph(dot)  # since remove_cycles changes G, thought bug might be due to it, but no
		while remove_cycle(dot, G):
			c += 1
			G = nx.nx_agraph.from_agraph(dot)
		if c > 1:
			print(f'Removed {c} cycles from dot graph')
		elif c == 1:
			print(f'Removed 1 cycle from dot graph')

	def singleparent(self, dot):
		def allbutone(dot, preds):
			# TODO: see if this always works: go by all but biggest (want longest), unless an *if, then go by Y
			# Consider this alternate: *goto's should be preds (maybe it will always be 1 or more gotos with the other pred being anything?)
			if len(preds) == 2:
				# want to be the Y branch to more closely imitate the way the code looks (so far only simple *if with not *else or *elif)
				if getnodetype(dot.get_node(preds[0])) == Type.cond:
					del(preds[0])
					return
				if getnodetype(dot.get_node(preds[1])) == Type.cond:
					del(preds[1])
					return
			elif len(preds) < 2:
				print('impossible')
				sys.exit(1)
			# all other cases
			# debug/planning: see what type preds can be. So far: all goto's, 1 goto and something else, so for now, consider removing the (a?) non-goto, and only fall back to the "always works?" guess below
			typescount = {}
			for i in preds:
				t = getnodetype(dot.get_node(i))
				print(f'preds: type is {t}')
				try:
					typescount[t] += 1
				except KeyError:
					typescount[t] = 1
			print(f'\n{typescount}\n')
			# count up non-gotos
			nongotos = 0
			for i in preds:
				t = getnodetype(dot.get_node(i))
				if t != Type.goto:
					nongotos += 1
			# debug
			try:
				if len(preds) - nongotos != typescount[Type.goto]:
					print('found something other than expected 2 cases (see above)')
					sys.exit(1)
			except KeyError:
				# no goto's. Happens in mygame-spcln in the *if *else stuff
				print('no gotos case')
			# remove the nongoto if there's only 1
			if nongotos == 1:
				for i in preds:
					t = getnodetype(dot.get_node(i))
					if t != Type.goto:
						print('removed a non-goto')
						preds.remove(i)
						return
			# fallback:
			print('fallback reached')  # happens in all gotos case (i.e. not a cond or a text (or whatever) falling thru)
			# all but biggest (want longest, always works?)
			preds.sort()
			del(preds[-1])

		# Convert dot to networkx for its additional analysis functions
		G = nx.nx_agraph.from_agraph(dot)  # wasteful as do this in remove_cycles too, but for some reason, when tried to generate it only once (and pass as a parm), it caused graph to split into two at guesspassword
		maxid = sorted(G.nodes, key=int)[-1]
		nextid = str(int(maxid)+1)
		for n2 in G.nodes:
			#print(list(G.predecessors(n2)))
			preds = list(G.predecessors(n2))
			if len(preds) > 1:
				otherparents = []
				allbutone(dot, preds)
				for n in preds:
					predstartln = dot.get_node(n).attr['startln']
					otherparents.append(predstartln)
					edgelabel = ''
					try:
						edgelabel = dot.get_edge(n, n2).attr['label']
					except IndexError:
						# fine if edge doesn't have a label
						inspect(dot.get_edge(n, n2))
						prompt('e')
						pass
					#print(f"{dot.get_node(n).attr['startln']}: {dot.get_node(n).attr['label']} / {dot.get_node(n).attr['shape']} - {edgelabel} -> {dot.get_node(n2).attr['startln']}: {dot.get_node(n2).attr['label']}")
					dot.remove_edge(n, n2)
					#dot.add_node(nextid, label=f'[bold yellow]{nextid}: [white]Goto {n2} ({n})')  # node id version
					startln = dot.get_node(n2).attr['startln']
					targetlabel = colorgoto(dot, n2)  # consists of label and startln or just startln if not label
					dot.add_node(nextid, label=f'[bold yellow]{predstartln}: [not bold white]Goto {targetlabel}')
					dot.get_node(nextid).attr['oldgoto'] = startln
					dot.get_node(nextid).attr['loopgoto'] = 1  # false
					if edgelabel:
						dot.add_edge(n, nextid, label=edgelabel)
					else:
						dot.add_edge(n, nextid)
					nextid = str(int(nextid)+1)
				# dot.get_node(n2).attr['otherparents'] = otherparents  # Hmm, seems list gets converted to str here???
				if otherparents:
					dot.get_node(n2).attr['otherparents'] = ' '.join(otherparents)  # so make a space-delimited string
				else:
					dot.get_node(n2).attr['otherparents'] = ''  #03/29/22-strange bug. Sometimes worked, then .split() in make_csnodes below errored out cuz was a list, so added this

	def make_csnodes(self, dot_acyclic):
		# pgv nodes to CStree nodes
		for i in dot_acyclic.nodes():  # could also use iternodes() or nodes_iter()
			self.nodes[i] = CSnode(i, self, guide_style="blue")

		# pgv edges to CStree edges
		maxid = -1
		for i in self.dot_acyclic.edges():
			id1 = i[0]
			id2 = i[1]
			startln = '-1'
			#print(f'edge {id1} -> {id2}')
			if len(self.nodes[id1].children) > 0:
				self.nodes[id2].prev = self.nodes[id1].children[-1]
				self.nodes[id1].children[-1].next = self.nodes[id2]
			self.nodes[id1].children.append(self.nodes[id2])
			self.nodes[id2].parent = self.nodes[id1]
			# Proc edge label, e.g. a #choice, Y or N for an *if, etc
			try:
				edge_label = i.attr['label']
			except AttributeError:
				# some edges don't have labels (only choice options do)
				edge_label = ''
			if i.attr['startln']:
				startln = i.attr['startln']
			else:
				# remove_cycles and/or singleparent create new nodes with no startln (only label)
				startln = -1
			if edge_label != '':
				self.nodes[id2].parent_edge_label = edge_label
				#self.nodes[id2].label_prepend('[orange3]' + edge_label)
				self.nodes[id2].label_prepend(colorlabel(startln, Type.option, edge_label))
			# Set maxid
			print(f'm: {maxid}, 1: {id1}, 2: {id2}')
			if int(id1) > int(id2) and int(id1) > maxid:
				maxid = int(id1)
				self.maxid = id1
			elif int(id2) > int(id1) and int(id2) > maxid:
				maxid = int(id2)
				self.maxid = id2

		# convert otherparents from startln to CSnode
		for node in self.nodes.values():
			print(f'make_csnodes: on {node.startln} (id: {node.id}) - {node.otherparents}')
			if node.otherparents:
				nodelist = []
				try:
					oplist = node.otherparents.split()
				except AttributeError:
					# 03/30/22-Strange bug still happening. Says list has no split().
					inspect(node, console=consolef)
					oplist = []  # assume this, but verify
				for startln in oplist:
					opnode = self.getln(startln)
					if opnode is not None:
						nodelist.append(opnode)
					else:
						print(f'No node has startln of {startln}. Other parents: {node.otherparents}')
						prompt()
				node.otherparents = nodelist
		#debug
		#for node in self.nodes.values():
		#	if node.parent is None:
		#	#if node.otherparents:
		#		inspect(node)
		#		prompt()

		# Add multi-parent count to label
		for k, node in self.nodes.items():
			if node.otherparents:
				node.append2toplabel(f' [grey37](Other links: {node.otherparents_str})')

		# Set cur and highlight it
		if self.cur is None:
			self.cur = self.nodes['0']
			self.cur.makecur()

	def readdot(self, dotfile):
		def fixemptylabels(dot_orig):
			dot = dot_orig.copy()
			for i in dot:
				#print(f"{i.attr['startln']} ({i}): {i.attr['label']}")
				if i.attr['label'] == '\\N':  # pgv.AGraph puts \N if there's no label
					#print('\tdid')
					i.attr['label'] = '*'	  # I guess just change it to an asterisk (shouldn't hardcode)
			return dot

		self.dot_orig = pgv.AGraph(dotfile, strict=False, directed=True)
		dot = fixemptylabels(self.dot_orig)
		self.remove_cycles(dot)
		self.singleparent(dot)
		self.dot_acyclic = dot
		self.make_csnodes(dot)
		#sys.s

	# Return the id where startln == linenum, else None. Also check linenum+1, cuz it happens
	def ln2id(self, linenum):
		# Return the id where startln == linenum, else None
		def _ln2id(linenum):
			for k, v in self.nodes.items():
				#print(f'if int({v.startln}) == {linenum}:')
				try:
					if int(v.startln) == linenum:
						return k
				except ValueError:
					# some nodes have no startln like new nodes created by remove_cycles and singleparent
					pass
			return None

		if type(linenum) is not int:
			linenum = int(linenum)
		# Return the node that corresponds to linenum, else None
		ret = _ln2id(linenum)
		# user might enter a startln that has no corresponding node, so look ahead
		if ret is None:
			linenum += 1
			ret = _ln2id(linenum)
		# Return id of linenum if exists, else id of linenum+1 if exists, else None
		return ret

	def getln(self, linenum):
		if type(linenum) is not int:
			linenum = int(linenum)
		try:
			return(self.nodes[self.ln2id(linenum)])
		except KeyError:
			# ln2id returns None sometimes (I think not anymore)
			print(f'ln2id returned None for {linenum}')
			print(f'len: {len(self.nodes)}')
			for i in self.nodes:
				print(f'{i} ', end='')
			print('')

	def inspectln(self, linenum):
		id = self.ln2id(linenum)
		if id is not None:
			inspect(self.nodes[id])
		else:
			print(f'Node {linenum} not found')

	def inspect_children_ln(self, linenum):
		id = self.ln2id(linenum)
		if id is None:
			print(f'Node {linenum} not found')
			return
		for child in self.nodes[id].children:
			inspect(child)

	def println(self, linenum, pager=False):
		# id = None
		# while id is None:
		#	# if linenum doesn't exist (like a blank line in the scene file), keep going forward... but... if never finds, becomes infinite loop...
		#	id = self.ln2id(linenum)
		#	linenum += 1
		id = self.ln2id(linenum)
		if id is not None:
			if pager:
				with console.pager(styles=True):
					console.print(self.nodes[id])
			else:
				print(self.nodes[id])
		else:
			print(f'Node {linenum} not found')

	# TODO: Var stuff into adjacent text block. Multi-parent into *choice's label.
	# DONE: #choices into the *choice. Empty *goto into target.
	def squash_goto(self):
		for k, v in self.nodes.items():
			if v.type == Type.goto:
				if v.parent.type == Type.choice:
					print(f'not squashing this goto ({v.startln}) on account of its parent being a choice, just modding label to remove 2nd renderable')
					if isinstance(v.label, Group):
						# could just (scary) del 2nd renderable in the label, but how 'bout matching it with its truelabel, just to be safe
						v.label.renderables.remove(v.truelabel)
						# self.parent.label_append(self.label)	# wrong. Node was a goto after an "edge" (i.e. a #option), and this will make it merge with the *choice (but other #options remained chidren of it)
						# TODO: need to be able to unsquash, i.e. put back the *?
					else:
						print('imp?')  # didn't happen, so can del?
				else:
					print('sg')
					v.squash()

	def squash_choice(self):
		for k, v in self.nodes.items():
			if v.type == Type.choice:
				print('cs')
				v.squash()

	def squash_label(self):
		for k, v in self.nodes.items():
			if v.type == Type.text:
				if v.parent is not None:
					#inspect(v)  # ah, was the *scene_list, which is indeed parentless, so this is ok
					if v.parent.type == Type.label:
						print(f'sl: {v.startln}')
						v.squash()
				#inspect(v)
				#inspect(v.parent)

	def squashall(self):
	# Iterate CStree to mod it (squash stuff).
		self.squash_goto()	# must be done before squash_choice, cuz squash_goto checks if parent is a *choice to work right. TODO: to fix, the check should look in parent's squasheds too, but why bother since I think I prefer not squashing choices anyway
		#self.squash_choice()  # I like that ?
		self.squash_label()

	# Put ... for groups of inconsequential nodes. Assumes allvars() called already.
	def hideall(self):
	# TODO: consider changing names for: squash (next node incorporated into current node), open/close (whole branch onward replaced by ...), and hide (next node replaced by ... only)
		def traverse(node):
			if node.children is None or len(node.children) == 0:  # None case is just in case, but should never happen (programmer paranoia)
				# do nothing, yes? (programmer confused)
				return
			# Recurse first
			for child in node.children:
				traverse(child)
			# Start from leaves on up. First, don't hide if child is a loop or multi goto
			if node.children and node.children[0].type in [Type.loopgoto, Type.multigoto]:
				return
			## Don't hide node if parent has multiple children
			#if node.parent and len(node.parent.children) > 1:
			#	return
			## Don't close choices
			#if node.type == Type.choice:  # why no work? They're still closing
			#	return
			## Don't close *labels
			#if node.type == Type.label:
			#	return
			## Don't close *set . Geez, not closing anything, so hideall not hiding much anymore :-(
			## And, I think if parent wants to hide, these will all get hidden anyway, so...
			#if node.type == Type.var and csexpr(node.plainlabel)[0] == 'SET':
			#	return
			# don't hide it if any vars on this node can have multiple values
			if not self.multival_all(node):
				for child in node.children:
					if self.multival_all(child):
						break
				else:
					# if above loop doesn't break
					node.hide(updatecur=False)  # so... leaf node will get rejected, but then its parent will hide it. Hmm, but if it comes to a node with a multival child, it'll slurp it up

					# debug
					#print(node.tree.nodes['0'])
					#prompt()

					#node.notcur()  # didn't work. Some ... nodes 3 [r]'s at start, one at end?!?

					# debug
					#consolef.print(f'l: {node.label}')
					#inspect(node.children[0].label, console=consolef)

		# start the recursion
		traverse(self.nodes['0'])
		# all recursive calls complete
		#node.label_append(str(node.vars))

	# traverse the cstree and return it in dot format
	def makedot(self, startid=0):
		#def summarize(node):
		#	print(f'\nsum top. type: ', node.type)
		#	if isinstance(node.label, Group):
		#		print(f'sum group{node.label}')
		#		ret = ''
		#		for label in node.label.renderables:
		#			print(f'str: {label}')
		#			label = nostyle(label)
		#			if label not in ['Y', 'N']:
		#				ret += nostyle(label)
		#		return ret
		#	else:
		#		print(f'sum not group {node.label}')
		#		return nostyle(node.label)

		def traverse(node):
			nonlocal dotstr
			# get dotnode
			try:
				#dotnode = self.dot_orig.get_node(node.id)
				dotnode = self.dot_acyclic.get_node(node.id)
			except KeyError:
				# node 56 was not in graph (both orig and acyclic) also 61... Ah, these are Type.hidenodes
				dotnode = None
			if dotnode:
				# if dotnode, use dotnode's attr's
				shape = dotnode.attr['shape']
				label = dotnode.attr['label']
				fillcolor = dotnode.attr['fillcolor']
				style = dotnode.attr['style']
				try:
					tooltip = dotnode.attr["tooltip"]
				except IndexError:
					tooltip = ''
			else:
				# these be hidenodes, so assign hidenode attr's
				#try:
				#	trueself = node.trueself
				#except AttributeError:
				#	consolef.print('no trueself, so node is something other than a ... hidenode, but what???')
				#	sys.exit(1)
				shape = 'box'
				label = node.plainlabel
				fillcolor = 'none'
				style = 'filled'
				#tooltip = summarize(trueself)
				tooltip = ''
				if node.hiddens:
					for hidstr in node.hiddens:
						tooltip += f'{hidstr}\n'
			border = ''
			if hasattr(node, 'multivars'):
				if node.multivars is not None:
					border = ' color=red penwidth=5'
					# style = f'"{style} bold"'  # didn't work despite: https://www.graphviz.org/doc/info/shapes.html
					if tooltip:
						tooltip += '\n' + node.multivars
					else:
						tooltip = node.multivars
				else:
					#inspect(node, console=consolef)
					print('will not happen')
					sys.exit(1)
			tooltip = f' tooltip="{tooltip}"'
			dotstr += f'\t{node.id} [label="{label}" shape={shape} fillcolor={fillcolor} style={style}{border}{tooltip}]\n'
			#if isinstance(node.label, Group):
			#	print(node.id, ': ', end='')
			#	print(node.label.renderables[0])
			#else:
			#	print(f'{node.id}: {node.label}')
			for child in node.children:
				#print(f'\t{child.id}: {child.type} - {child.label}')
				#if isinstance(child.label, Group):
				#	print(f'\t', child.label.renderables[0], end='')
				#else:
				#	print(f'\t {child.label}', end='')
				#print(' - ', child.type)
				if child.type == Type.multigoto:
					child = self.getln(child.oldgoto)
					try:
						pedge = f' [label="{child.parent_edge_label}"]'
					except AttributeError:
						pedge = ''  # most in fact do not have
					dotstr += f'\t{str(node.id)} -> {str(child.id)}{pedge}\n'
				else:
					try:
						pedge = f' [label="{child.parent_edge_label}"]'
					except AttributeError:
						pedge = ''  # most in fact do not have
					dotstr += f'\t{str(node.id)} -> {str(child.id)}{pedge}\n'
					# only traverse once, i.e. not a goto (loopgoto's not in this at all. Ok?)
					traverse(child)
		dotstr = 'digraph {\n'
		traverse(self.nodes[str(startid)])
		dotstr += '}\n'
		return dotstr

	# Write new graphviz code to a file
	def cs2dot(self, filename="newdot.dot", startid=0):
		dotstr = self.makedot(startid)
		with open(filename, "wt") as f:
			f.write(dotstr)

	# this iterates self.nodes, which is wrong. Do tree traversal instead (above)
	def cs2dot_wrong(self):
		dotstr = 'digraph {\n'
		for key, node in self.nodes.items():
			dotstr += f'\t{str(key)}\n'
			for child in node.children:
				dotstr += f'\t{str(key)} -> {str(child.id)}\n'
		dotstr += '}\n'
		with open("newdot.dot", "wt") as f:
			f.write(dotstr)

	# Traverse whole tree and give each node its vars (starts at nodes[0], so unconnected parts missed)
	# Also fills in self.allvarnames
	def allvars(self):
		# Given a node, recursively traverse all its children, collecting all vars (allows erroneous choicescript, no randoms, just basic + and - a number (not another var) for *set for now. In future, maybe call js: https://stackoverflow.com/questions/39096901/call-javascript-from-python )

		# TODO: bug: if run this when there's a closed node (openclose()) get AttributeError: Ctree has no attr vars (caused on line with node.vars

		# make var table, vars first, yellow on grey, line between vars, only print var name once
		def traverse(node, curpath, curvars):
			# merge vars2 (vars coming in from previous nodes) into vars1 (vars node already has)
			def merge(vars1, vars2):
				vars2 = copy.deepcopy(vars2)  # got: for path1, val1 in paths1.items(): RuntimeError: dictionary changed size during iteration , so tried this, but didn't fix, so maybe don't need, but leave just in case, because lazy
				for var2, paths2 in vars2.items():
					#print(f'var2={var2}')
					if var2 in vars1.keys():
						for path2, val2 in paths2.items():
							#print(f'\tpath2={path2}, val2={val2}')
							for var1, paths1 in vars1.items():
								#print(f'\t\tvar1={var1}')
								if var1 == var2:
									paths1 = paths1.copy()
									for path1, val1 in paths1.items():
										#print(f'\t\t\tpath1={path1}, val1={val1}')
										# Check if we've been here before
										# TODO: I worry might get into infinite loop, but maybe that possibility handled in remove_cycles()? For now, that is, but eventually, should allow a few (how many?) to see if any vars change
										if path2 == path1 and val2 == val1:
											# so far, has happened when two ways to get to END on same branch. I guess nothing to do
											#print('been here before')
											pass
										#elif path2.startswith(path1):
										#	# paths are different (same at first, then diverged, but... this is *always* true. Hmm...), so values might be different
										#	print(f'{var2} already exists in node {node.startln}, loop kind')
										#	prompt()
										else:
											#print(f'{var2} already exists in node {node.startln}, but came by diff path, so add it too, even if value is the same')
											vars1[var1][path2] = val2
					else:
						# incoming var not in node yet, so just copy it on over
						vars1[var2] = paths2.copy()
			# End def merge()

			def ifchildren(node):
				if node.type != Type.cond:
					raise
				for child in node.children:
					pedge = ''
					if hasattr(child, 'oldgoto'):
						# It's a goto, but before going, need parent_edge_label
						if child.parent_edge_label:
							pedge = child.parent_edge_label
						child = self.getln(child.oldgoto)
					if child.parent_edge_label == 'Y' or pedge == 'Y':
						truechild = child
					elif child.parent_edge_label == 'N' or pedge == 'N':
						falsechild = child
					else:
						#inspect(child)
						prompt('WTF is up with this child?')
				return truechild, falsechild
			# End ifchildren()

			# Add back children that singleparent() removed (in a copy of children) and return it
			def includegotos(node):
				# TODO: DONE but test: potential bug but seems working: this doesn't remove the goto child itself
				#allchildren = node.children.copy()
				allchildren = []
				for child in node.children:
					if hasattr(child, 'oldgoto'):
						allchildren.append(self.getln(child.oldgoto))
					else:
						allchildren.append(child)
				return allchildren
			# End def includegotos(), End sub-functions

		# Begin traverse() main code proper:
			# TODO: check if node closed by openclose() here and use correct node, not fake ... node
			# All nodes get all previous vars added to them
			#print(f'{node.startln}: merging node\'s previous vars {node.vars} with curvars {curvars}')
			merge(node.vars, curvars)
			#print(f'so now, node vars are {node.vars}')  # node may have had no vars if first time being iterated, or could have some if visited already
			# In addition, var nodes modify curvars and node.vars
			#print(f'[yellow]Processing node: {node.startln}')
			if node.type == Type.var:
				# make new curpath (tack on new startln, save previous to oldcurpath)
				oldcurpath = curpath
				if curpath:
					curpath += f'.{node.startln}'
				else:
					curpath = f'{node.startln}'
				# When come to another var node, update all node.vars's paths (their indices) to append the new startln
				for var, paths in node.vars.items():
					for path, val in paths.copy().items():
						if path == oldcurpath:
							#print(f'updating node\'s {path}:{var} to {curpath}')
							del node.vars[var][path]
							node.vars[var][curpath] = val
						else:
							#print(f'failed updating {path}:{var} to {curpath} because needed path to be {oldcurpath}, but this is fine (i.e. stop showing this message) as it just means came to the node again, so it (changing the path) was done already')
							pass
				# also update all curvars's paths (their indices)
				for var, paths in curvars.items():
					for path, val in paths.copy().items():
						if path == oldcurpath:
							#print(f'updating curvars\'s {path}:{var} to {curpath}')
							del curvars[var][path]
							curvars[var][curpath] = val
						else:
							# getting here is um, possibly... impossible?
							print(f'Updating curvars: failed updating {path}:{var} to {curpath}')
							prompt()
				# split the *set/*create/etc into cmd, varname, and varvalue tokens
				#tokens = node.plainlabel.split()
				#cmd = tokens[0]
				#varname = tokens[1]
				#varvalue = ''.join(tokens[2:])	# so "+ 1" becomes "+1"
				cmd, varname, varvalue, valuestr = csexpr(node.plainlabel)
				# Add/update the var to/in node.vars
				if varname in node.vars.keys():
					#print(f'{varname} exists already and has value {node.vars[varname]}')
					if cmd == 'SET':
						# iterate all var-paths for this var and do the *set on each one
						for path in node.vars[varname].copy():
							#print(f'setting {varname} to {varvalue} (path={path}) (was: {node.vars[varname][path]})')
							# calculate new result
							#print(f'[yellow]{node.startln}:[default] ', end='')
							result, arrowstr = seteval(node.plainlabel, curvars)
							# put in new var-path
							oldval = node.vars[varname][path]
							node.vars[varname][path] = str(oldval) + arrowstr  # for testing, still arrow form
							#node.vars[varname][curpath] = result  # use this after test phase (and del oldval)
							#print(f'{varname} in node: {node.vars[varname]}')
							curvars[varname][path] = result
							#inspect(path)
					else:
						print(f'creating a var that already exists? {varname}')
				else:
					#print(f'{varname} not yet seen')
					if cmd != 'SET':  # i.e. CREATE or TEMP
						self.allvarnames.append(varname)
						curvars[varname] = {}
						curvars[varname][curpath] = valuestr
						# node.vars[varname] = copy.deepcopy(curvars)[varname]	# tried deepcopy due to mysterious reference/not value error
						node.vars[varname] = curvars[varname].copy()  # had this originally. Put back. Seems to work now.
						#node.vars[varname] = curvars[varname]	# even this seems to work??? I'm too leery...
						#print(f"setting node's {varname} to {curvars[varname]} = {node.vars[varname]}")
						# set var's color
						self.varcolors[varname] = next(self.colorcycle)

					else:
						print(f'setting a var before creation? {varname}')
				# debug
				#inspect(node)
				#print('curvars after: ', curvars)
				#prompt()

				# debug
				#print(' Recurse children')
				#for child in node.children:
				#	inspect(child)
				#print('with gotos')
				#for child in includegotos(node):
				#	inspect(child)
				#prompt()

				# Recurse children
				for child in includegotos(node):
					# TODO: what about goto's remove_cycles takes out?
					traverse(child, curpath, copy.deepcopy(curvars))
			elif node.type == Type.cond:
				truechild, falsechild = ifchildren(node)
				if ifeval(node.plainlabel, curvars):
					traverse(truechild, curpath, copy.deepcopy(curvars))
				else:
					traverse(falsechild, curpath, copy.deepcopy(curvars))
			else:
				# Recurse children
				# for child in node.children:
				for child in includegotos(node):
					# TODO: what about goto's remove_cycles takes out?
					traverse(child, curpath, copy.deepcopy(curvars))

		# start the recursion
		traverse(self.nodes['0'], '', {})
		# all recursive calls complete
		#node.label_append(str(node.vars))

	# (short version calls showvars() on every node. Not short version is my first version. Useless? Sorted by varname first, shows: varname, path, value. Puts underline when varname changes to separate (looks bad; too close to top one; oh, and WTF, thought it was working but no, just underlines each line geez)
	def showallvars(self, short=True):
		def maketablebyvar(node):
			oldvar = ''
			tablevars = []
			for var, paths in node.vars.items():
				for path, val in paths.copy().items():
					if var != oldvar:
						oldvar = var
						tablevars.append([var, path, str(val)])
					else:
						tablevars.append(['', path, str(val)])
			# fix up table
			table = Table(show_lines=False, show_header=False, box=None)
			prevrow = None
			for row in tablevars:
				if prevrow is not None:
					if row[0] != '':
						# new var appears means previous row is underlined
						table.add_row(prevrow[0], prevrow[1], prevrow[2], style=Style(color='yellow', bgcolor='grey37', underline=True))
					else:
						# all other cases, no underline
						table.add_row(prevrow[0], prevrow[1], prevrow[2], style=Style(color='yellow', bgcolor='grey37', underline=True))
				prevrow = row
			# add final row
			try:
				table.add_row(row[0], row[1], row[2], style=Style(color='yellow', bgcolor='grey37'))
			except UnboundLocalError:
				# node might not have any vars yet
				pass
			return table
		# End def maketablebyvar()

		if short:
			for k, node in self.nodes.items():
				node.showvars()
		else:
			for k, node in self.nodes.items():
				table = maketablebyvar(node)
				#prompt('t')
				node.label_append(table)

	# show vars on nodes of Type.var and if node has multiple parents (useless and cluttered, delme)
	def showimportantvars(self):
		for k, node in self.nodes.items():
			if node.type == Type.var or len(node.otherparents) > 0:
				node.showvars()
	# show vars on these nodes only: *if, *set, and multi-parent. Only relevant vars for *if and *set. (Still shows some unnecessary, so making version 3 below. Delme)
	def showimportantvars2(self):
		# looks in a *set or *if expression and returns list of all var names found in it
		def findvarnames(rest):
			# TODO: no need to do this in 2 steps, just combine rest[0] and rest[1] into a single list
			vars = []
			if len(rest) != 3:
				print('bad command')
				sys.exit(1)
			varname = rest[0]
			# add var if varname is in allvarnames.
			if varname in self.allvarnames:
				vars.append(varname)
			else:
				print(f"var doesn't exist: {varname}")
				sys.exit(1)
			# add var if var appears anywhere in the expression too
			varvalue = rest[1]
			valuestr = rest[2]  # not even used here
			for token in varvalue:
				if token in self.allvarnames:
					vars.append(token)
			return vars

		for k, node in self.nodes.items():
			#inspect(node)
			cmd, *rest = csexpr(node.plainlabel)
			# if node.type == Type.var or node.type == Type.cond:  # nah, just go by cmd
			# Cases when we want to show node's vars
			if len(node.otherparents) > 0 or cmd == 'SET' or cmd == 'IF':  # TODO: consider future case when *else, etc are also supported
				# *set and *if show only relevant vars (*create and *temp don't show vars at all)
				if cmd == 'SET' or cmd == 'IF':
					# find relevant vars
					vars_in_set = findvarnames(rest)
					showvars = []
					for var in node.vars:
						#print(f'checking if "{var}" is in "{node.plainlabel}"...', end='')
						if var in vars_in_set:
							showvars.append(var)
					if cmd == 'IF':
						# *if shows relevant vars in short form
						node.showvars(showvars, short=True)
					else:  # assumes SET
						# *set shows relevant vars in path form
						node.showvars(showvars)
				else:  # assumes multi-parent case
					# multi-parent nodes show all possible var paths (relevancy not considered at all)
					node.showvars()

	# Return True if and only if var at this node can have > 1 value
	def multival(self, node, var):
		oldval = None
		try:
			node.vars[var]
		except KeyError:
			# node.vars was {}. Return False if var not even in node.vars
			#inspect(node)
			return False

		# check for multiple values
		for path, val in node.vars[var].items():
			if oldval is None:
				oldval = val
			elif val != oldval:
				return True
		return False

	# Return True iff node has at least one var with > 1 value
	def multival_all(self, node):
		for var in node.vars.keys():
			if self.multival(node, var):
				return True
		return False

	# show vars on these nodes only: *if, *set, and multi-parent. Only relevant vars for *if and *set, and only if came in with multiple values. Multi-parent only vars with multiple values.
	# this also adds attribute multivars to the node
	def showimportantvars3(self):
		# looks in a *set or *if expression and returns list of all var names found in it
		def findvarnames(rest):
			vars = []
			if len(rest) != 3:
				print('bad command')
				sys.exit(1)
			rest = [rest[0]] + rest[1]  # varname and varvalue (no cmd, no valuestr)
			for token in rest:
				if token in self.allvarnames:
					vars.append(token)
			return vars

		for node in self.nodes.values():
			#inspect(node)
			cmd, *rest = csexpr(node.plainlabel)
			showvars = []
			# Cases when we want to show node's vars
			# Show vars if > 1 parent and can have different values
			if len(node.otherparents) > 0:
				# Set showvars to vars with more than one possible value for this node
				for var in node.vars:
					if self.multival(node, var):
						showvars.append(var)
			elif cmd == 'SET' or cmd == 'IF':  # TODO: consider future case when *else, etc are also supported
				# Show vars on *set and *if, only if a var in it has multiple values
				# find relevant vars
				vars_in_set = findvarnames(rest)
				for var in vars_in_set:
					#print(f'checking if "{var}" is in "{node.plainlabel}"...', end='')
					if self.multival(node, var):
						showvars.append(var)
			# show vars in proper format if any are relevant on this node
			if cmd == 'IF':
				# *if shows relevant vars in short form
				node.showvars(showvars, short=True)
				multivars = node.showvars(showvars, short=True, perline=True, nolabel=True)
				if multivars is not None:
					node.multivars = nostyle(multivars)
			else:  # SET and multi-parent case, shows relevant vars in path form
				node.showvars(showvars)
				multivars = node.showvars(showvars, perline=True, nolabel=True)
				if multivars is not None:
					node.multivars = nostyle(multivars)

	async def interactive(self) -> None:
		done = asyncio.Event()
		input = create_input()
		# can I get a prompt while also the async no-prompt thing? (See: https://python-prompt-toolkit.readthedocs.io/en/master/pages/asking_for_input.html )
		session = PromptSession()

		# Async prompt
		q = asyncio.Queue()

		async def getlabel(p):
			with patch_stdout():
				newlabel = await session.prompt_async('Say something: ')

		# Async read keypresses without prompt
		# Process keypresses
		def keys_ready():
			nonlocal cmd
			for key_press in input.read_keys():
				print(key_press)
				if key_press.key == Keys.ControlC or key_press.key == Keys.ControlD:
					cmd = 'quit'
					done.set()
				elif key_press.key == 'up' or key_press.key == 'k':
					if self.nodes[self.cur.id].goprev() is not None:
						print(self.nodes['0'])
					else:
						print("Cannot prev()")
				elif key_press.key == 'down' or key_press.key == 'j':
					if self.nodes[self.cur.id].gonext() is not None:
						print(self.nodes['0'])
					else:
						print("Cannot next()")
				elif key_press.key == 'right' or key_press.key == 'l':
					if self.nodes[self.cur.id].gochildren() is not None:
						print(self.nodes['0'])
					else:
						print("Cannot children()")
				elif key_press.key == 'left' or key_press.key == 'h':
					if self.nodes[self.cur.id].goparent() is not None:
						print(self.cur.label)
						print(self.nodes['0'])
					else:
						print("Cannot parent()")
				elif key_press.key == 'a':
					# Add node
					cmd = 'add'
					done.set()
				elif key_press.key == 'd':
					# Delete node
					self.cur.notcur()
					newcur = self.cur.parent
					self.cur.parent.children.remove(self.cur)
					self.cur = newcur
					newcur.makecur()
					print(self.nodes['0'])
				elif key_press.key == 'c' or key_press.key == 'o':
					# Close or open (toggle, I guess)
					self.cur.openclose()
					print(self.nodes['0'])
				elif key_press.key == 'i':
					inspect(self.cur)
		# End get_keys()

	# Start interactive() proper:
		# First time going interactive, so set self.cur and highlight it. (Delme, as already done in make_csnodes.) Otherwise, will still be
		if self.cur is None:
			self.cur = self.nodes['0']
			self.cur.makecur()

		# Start off by printing tree
		print(self.nodes['0'])

		# Main loop
		cmd = ''
		while True:
			# Wait for keypress events
			with input.raw_mode():
				with input.attach(keys_ready):
					await done.wait()
			# User was in no prompt mode, but came out now
			if cmd == 'quit':
				print("End interactive mode")
				break  # end interactive() mode (goes back to testloop() for now)
			elif cmd == 'add':
				newlabel = await session.prompt_async('> ')
				newid = self.nextid()
				self.cur.add(newid, newlabel)  # TODO: add must add to nodes, update other things?, etc
				print(self.nodes[0])
				cmd = 'none'
				done.clear()
	# End self.interactive()

	def newnode(self, label):
		newnode = CSnode(self.nextid(), self)
		# TODO: check labels (like for no [styles] in plainlabel)
		newnode.label = label
		newnode.plainlabel = label
		newnode.truelabel = label
		self.nodes[newnode.id] = newnode
		return newnode

	# Decided not to do it this way
	#def showvarsln(self, ln, short=False, perline=False):
	#	showln = self.getln(ln)
	#	if not isinstance(self.label, Group):
	#		return None
	#	labels = iter(self.label)
	#	while showln is None:
	#		# iterate in label
	#		showln = self.getln(

	def testloop(self, promptstr=': '):
		def testprompt(promptstr):
			try:
				return sess.prompt(promptstr).strip()
			except KeyboardInterrupt:
				# continue  # abort command
				sys.exit()
			except EOFError:
				sys.exit()

		def getln(promptstr):
			nonlocal ln
			if ln is not None:
				return ln
			else:
				return int(sess.prompt(promptstr))

		def help():
			print("""
[bold yellow]CStree![not bold white] Now you can finally visualize your ChoiceScript story-games and see at a glance all the combinations of values your stats can be.

[yellow]Commands take one of the following forms:[white]

[blue]11, a, 11a, a11, a 11[white]

A number by itself means to print the CStree in a pager. A number paired with a command ('a' in the examples above) is that command's parameter. If a command that requires a parameter is entered by itself, a prompt for that parameter appears.

[bold yellow]Command List:[not bold blue] g l s c p o av va vl v vs i[white]

	[blue]g[white] = squash gotos
	[blue]l[white] = squash labels (print whole tree if already squashed labels)
	[blue]s[white] = squash all (gotos and labels by default, not choices)
	[blue]c[white] = squash choices
	[blue]p[white] = print tree (takes the line number as its parameter, doesn't use the pager)
	[blue]o[white] = open/close
	[blue]C[white] = close all inconsequential nodes
	[blue]av[white] = compute all variables
	[blue]va[white] = add variables to each node (print tree to see)
	[blue]vl[white] = add long-form variables to each node
	[blue]v[white] = add variables to a single node
	[blue]vs[white] = add variables to a single node, short-form
	[blue]vi[white] = add variables to "important" nodes (*set, etc)
	[blue]i[white] = inspect a node
	[blue]dot[white] = view original tree in graphviz
	[blue]dota[white] = view original tree in graphviz (acyclic)
	[blue]dotc[white] = view graphviz of current tree
""")

		labeledalready = False
		squashed = False
		cmdln = None

		print("[bold]Welcome to CStree.[not bold] Enter 'h' or '?' for help. Enter 'q' (or ctrl-c or ctrl-d) to quit.")

		while True:
			if cmdln is not None:
				cmd = cmdln[0]
				ln = cmdln[1]
				cmdln = None
			else:
				cmd = testprompt(promptstr)
				try:
					ln = int(cmd)
				except:
					ln = None
			#print(f'l: {ln}, c: {cmd}')
			if ln is not None and re.match(r'\d+', cmd):
				# just an int defaults to printing tree from that line on (in pager)
				self.println(ln, pager=True)
			elif re.match(r'([a-z])\s*(\d+)', str(cmd)):
				# v3, v 3
				cmdln = re.match(r'([a-z])\s*(\d+)', cmd).groups()
				print(cmdln)
			elif cmd == 'g':
				self.squash_goto()
			elif cmd == 'l':
				if not labeledalready:
					self.squash_label()
					labeledalready = True
				else:
					self.println(0, pager=True)
			elif cmd == 's':
				if not squashed:
					self.squash_goto()
					self.squash_label()
					squashed = True
				else:
					print('s command after squash still TODO')
			elif cmd == 'c':
				self.squash_choice()
			elif cmd == 'p':
				ln = getln('print> ')
				print(ln)
				self.println(ln)
			elif cmd == 'o':
				ocln = getln('openclose> ')
				try:
					self.getln(ocln).openclose()
				except AttributeError:
					# getln returns None if no such node (like for #options)
					print('No such node')
					continue
			elif cmd == 'C':
				self.hideall()
			elif cmd == 'av' or cmd == 'allvars':
				self.allvars()
			elif cmd == 'va':
				self.showallvars()
			elif cmd == 'vl':
				self.showallvars(short=False)  # useless?
			elif cmd == 'v':
				ln = getln('vars> ')
				self.showvarsln(ln)
			elif cmd == 'vs':
				ln = getln('vars-short> ')
				self.showvarsln(ln, short=True)
			elif cmd == 'vn':
				ln = getln('vars-newline> ')
				self.showvarsln(ln, perline=True)
			elif cmd == 'vsn':
				ln = getln('vars-short-newline> ')
				self.showvarsln(ln, short=True, perline=True)
			elif cmd == 'ovp':  # o = old/obsolete
				ln = getln('vars-perline> ')
				self.showvarsln_perline()  # useless but possible alternate colorscheme
			elif cmd == 'vi':
				self.showimportantvars()
			elif cmd == 'vii':
				self.showimportantvars2()
			elif cmd == 'viii':
				self.showimportantvars3()
			elif cmd == 'i':
				asyncio.run(self.interactive())
			elif cmd == 'inspc':
				# inspect children
				ln = getln('inspect> ')
				self.inspect_children_ln(ln)
			elif cmd == 'in':
				ln = getln('inspect> ')
				self.inspectln(ln)
			elif cmd == 'list':
				for k, v in self.nodes.items():
					print(f'{k}: ', v.label, end='')
					if v.label == '...':
						if hasattr(v, 'parent_edge_label'):
							print(f' \[pedge: {v.parent_edge_label}] ', end='')
						else:
							print(f' \[no pedge] ', end='')
						print(v.hiddens)
					else:
						print('')
			elif cmd == 'ii':
				id = prompt('inspect by id> ')
				inspect(self.nodes[id])
			elif cmd == 'dp':
				# debug pedges
				for k, v in self.nodes.items():
					if hasattr(v, 'parent_edge_label'):
						print(f'{k}: ', v.label, end='')
						print(f' \[pedge: {v.parent_edge_label}] ')
						#print(v.hiddens)
			elif cmd == 'dot':
				self.dot_orig.layout(prog='dot')  # default is neato (upside-down)
				#dot.draw('test.png', prog='neato')  # circo is left to right and circular
				self.dot_orig.draw('test.png')
				os.system('sxiv test.png')
			elif cmd == 'dota':
				self.dot_acyclic.layout(prog='dot')
				self.dot_acyclic.draw('test.png')
				os.system('sxiv test.png')
			elif cmd == 'dotc':
				# output and show the graph in sxiv (just for testing. dotw or D below is better)
				self.dot_current = self.makedot()
				self.dot_current = pgv.AGraph(self.dot_current, strict=False, directed=True)
				self.dot_current.layout(prog='dot')
				self.dot_current.draw('test.png')
				os.system('sxiv test.png')
			elif cmd == 'dotw' or cmd == 'D':
				self.cs2dot()
				os.system('PYTHONPATH=/home/kanon/util/xdot.py python3 -m xdot newdot.dot')
			elif cmd == 'h' or cmd == '?':
				help()
			elif cmd == 'q':
				print('bye!')
				break
			elif cmd == '':
				continue
			else:
				print('Huh?')
