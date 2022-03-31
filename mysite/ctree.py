# Implements class Ctree. C = connected, meaning it has parent, next, and prev properties, not just children.
# A Ctree also adds these additional properties: plainlabel, truelabel, closed
# New method: openclose()
# A Ctree inherits from Rich's Tree class.

from rich.tree import Tree
from rich.console import Group
from rich import print
from rich import inspect

# Add next, prev, parent, and new methods for traversal to Tree class
class Ctree(Tree):
	def __init__(
		self,
		label,
		*,
		style = "tree",
		guide_style = "tree.line",
		expanded: bool = True,
		highlight: bool = False,
		hide_root: bool = False,
	) -> None:
		Tree.__init__(self, label=label, style=style, guide_style=guide_style, expanded=expanded, highlight=highlight, hide_root=hide_root)
		#super().__init__()  # equivalent?
		if isinstance(label, Group):
			if len(label.renderables) > 0:
				self.plainlabel = label.renderables[0]
				self.truelabel = label.renderables[0]
			else:
				self.plainlabel = '<no label>'
				self.truelabel = '<no label>'
		else:
			self.plainlabel = label
			self.truelabel = label
		self.next = None
		self.prev = None
		self.parent = None
		self.closed = False

	def add(
		self,
		label,
		*,
		style = None,
		guide_style = None,
		expanded: bool = True,
		highlight: bool = False,
	) -> "Ctree":
		# Make new node
		node = Ctree(
			label,
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
