# ###################################################
# Copyright (C) 2011 The Unknown Horizons Team
# team@unknown-horizons.org
# This file is part of Unknown Horizons.
#
# Unknown Horizons is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the
# Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
# ###################################################

import logging

from fife.extensions import pychan

import horizons.main

from horizons.gui.widgets.imagefillstatusbutton import ImageFillStatusButton
from horizons.gui.widgets.buysellinventory import BuySellInventory
from horizons.util.gui import load_uh_widget
from horizons.command.uioptions import SellResource, BuyResource
from horizons.util import Callback

class InternationalTradeWidget(object):
	log = logging.getLogger("gui.internationaltradewidget")

	# objects within this radius can be traded with, only used if the
	# main instance does not have a radius attribute
	radius = 5

	# map the size buttons in the gui to an amount
	exchange_size_buttons = {
	  1 : 'size_1',
	  5 : 'size_2',
	  10: 'size_3',
	  20: 'size_4',
	  50: 'size_5'
	  }

	images = {
	  'box_highlighted': 'content/gui/icons/ship/smallbutton_a.png',
	  'box': 'content/gui/icons/ship/smallbutton.png'
	  }

	def __init__(self, instance):
		"""
		@param instance: ship instance used for trading
		"""
		self.widget = load_uh_widget('buy_sell_goods.xml')
		self.widget.position_technique = "right:top+157"
		events = {}
		for k, v in self.exchange_size_buttons.iteritems():
			events[v] = Callback(self.set_exchange, k)
		self.widget.mapEvents(events)
		self.instance = instance
		self.partner = None
		self.set_exchange(50, initial=True)
		self.draw_widget()
		if hasattr(self.instance, 'radius'):
			self.radius = self.instance.radius

	def draw_widget(self):
		self.widget.findChild(name='ship_name').text = unicode(self.instance.name)
		self.partners = self.find_partner()
		if len(self.partners) > 0:
			partner_label = self.widget.findChild(name='partners')
			nearest_partner = self.get_nearest_partner(self.partners)
			partner_label.text = unicode(self.partners[nearest_partner].settlement.name)
			old_partner = self.partner
			self.partner = self.partners[nearest_partner]
			# If we changed partners, update changelisteners
			if old_partner and old_partner is not self.partner:
				old_partner.inventory.remove_change_listener(self.draw_widget)
				self.partner.inventory.add_change_listener(self.draw_widget)

			selling_inventory = self.widget.findChild(name='selling_inventory')
			selling_inventory.init(self.instance.session.db, self.partner.inventory, self.partner.settlement.sell_list, True)
			for button in self.get_widgets_by_class(selling_inventory, ImageFillStatusButton):
				button.button.capture(Callback(self.transfer, button.res_id, self.partner.settlement, True))

			buying_inventory = self.widget.findChild(name='buying_inventory')
			buying_inventory.init(self.instance.session.db, self.partner.inventory, self.partner.settlement.buy_list, False)
			for button in self.get_widgets_by_class(buying_inventory, ImageFillStatusButton):
				button.button.capture(Callback(self.transfer, button.res_id, self.partner.settlement, False))

			inv = self.widget.findChild(name='inventory_ship')
			inv.init(self.instance.session.db, self.instance.inventory)
			for button in self.get_widgets_by_class(inv, ImageFillStatusButton):
				button.button.capture(Callback(self.transfer, button.res_id, self.partner.settlement, False))
			self.widget.adaptLayout()
		else:
			self.widget.hide()

	def __remove_changelisteners(self):
		self.instance.remove_change_listener(self.draw_widget)
		self.partner.inventory.remove_change_listener(self.draw_widget)
		# TODO: partner buy / sell list

	def __add_changelisteners(self):
		self.instance.add_change_listener(self.draw_widget)
		self.partner.inventory.add_change_listener(self.draw_widget)
		# TODO: partner buy / sell list

	def set_partner(self, partner_id):
		self.partner = self.partners[partner_id]

	def hide(self):
		self.widget.hide()
		self.__remove_changelisteners()

	def show(self):
		self.widget.show()
		self.__add_changelisteners()

	def set_exchange(self, size, initial=False):
		"""
		Highlight radio button with selected amount and deselect old highlighted.
		@param initial: bool, use it to set exchange size when initing the widget
		"""
		if not initial:
			old_box = self.widget.findChild(name= self.exchange_size_buttons[self.exchange])
			old_box.up_image = self.images['box']

		box_h = self.widget.findChild(name= self.exchange_size_buttons[size])
		box_h.up_image = self.images['box_highlighted']

		self.exchange = size
		self.log.debug("Tradewidget: exchange size now: %s", size)
		if not initial:
			self.draw_widget()

	def transfer(self, res_id, settlement, selling):
		"""Buy or sell the resources"""
		if self.instance.position.distance(settlement.branch_office.position) <= self.radius:
			if selling:
				self.log.debug('InternationalTradeWidget : %s/%s is selling %d of res %d to %s/%s', \
					self.instance.name, self.instance.owner.name, self.exchange, res_id, settlement.name, settlement.owner.name)
				SellResource(settlement, self.instance, res_id, self.exchange).execute(self.instance.session)
			else:
				self.log.debug('InternationalTradeWidget : %s/%s is buying %d of res %d from %s/%s', \
					self.instance.name, self.instance.owner.name, self.exchange, res_id, settlement.name, settlement.owner.name)
				BuyResource(settlement, self.instance, res_id, self.exchange).execute(self.instance.session)
			# update gui
			self.draw_widget()

	def get_widgets_by_class(self, parent_widget, widget_class):
		"""Gets all widget of a certain widget class from the tab. (e.g. pychan.widgets.Label for all labels)"""
		children = []
		def _find_widget(widget):
			if isinstance(widget, widget_class):
				children.append(widget)
		parent_widget.deepApply(_find_widget)
		return children

	def find_partner(self):
		"""find all partners in radius"""
		partners = []
		branch_offices = self.instance.session.world.get_branch_offices(self.instance.position, self.radius, self.instance.owner, True)
		if branch_offices is not None:
			partners.extend(branch_offices)
		return partners

	def get_nearest_partner(self, partners):
		nearest = None
		nearest_dist = None
		for partner in partners:
			if partner.owner is not self.instance.owner: # international trade ignored domestic branch offices
				dist = partner.position.distance(self.instance.position)
				nearest = partners.index(partner) if dist < nearest_dist or nearest_dist is None else nearest
				nearest_dist = dist if dist < nearest_dist or nearest_dist is None else nearest_dist
		return nearest
