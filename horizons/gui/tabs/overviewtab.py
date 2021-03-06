# -*- coding: utf-8 -*-
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

import weakref

from fife.extensions import pychan

from tabinterface import TabInterface

from horizons.scheduler import Scheduler
from horizons.util import Callback, ActionSetLoader, NamedObject
from horizons.constants import GAME_SPEED, RES, SETTLER, BUILDINGS
from horizons.gui.widgets  import TooltipButton, DeleteButton
from horizons.gui.widgets.unitoverview import StanceWidget
from horizons.command.production import ToggleActive
from horizons.command.building import Tear
from horizons.command.uioptions import SetTaxSetting
from horizons.gui.widgets.imagefillstatusbutton import ImageFillStatusButton
from horizons.util.gui import load_uh_widget, create_resource_icon
from horizons.entities import Entities

class OverviewTab(TabInterface):
	def __init__(self, instance, widget = 'overviewtab.xml', \
	             icon_path='content/gui/icons/tabwidget/common/building_overview_%s.png'):
		super(OverviewTab, self).__init__(widget)
		self.instance = instance
		self.init_values()
		self.button_up_image = icon_path % 'u'
		self.button_active_image = icon_path % 'a'
		self.button_down_image = icon_path % 'd'
		self.button_hover_image = icon_path % 'h'
		self.tooltip = _("Overview")

		# set player emblem
		if self.widget.child_finder('player_emblem'):
			if self.instance.owner is not None:
				self.widget.child_finder('player_emblem').image =  \
			    'content/gui/images/tabwidget/emblems/emblem_%s.png' %  self.instance.owner.color.name
			else:
				self.widget.child_finder('player_emblem').image = \
			    'content/gui/images/tabwidget/emblems/emblem_no_player.png'


	def refresh(self):
		if hasattr(self.instance, 'name') and self.widget.child_finder('name'):
			name_widget = self.widget.child_finder('name')
			# Named objects can't be translated.
			if isinstance(self.instance, NamedObject):
				name_widget.text = self.instance.name
			else:
				name_widget.text = _(self.instance.name)

		if hasattr(self.instance, 'running_costs') and \
		   self.widget.child_finder('running_costs'):
			self.widget.child_finder('running_costs').text = \
			    unicode( self.instance.running_costs )

		self.widget.adaptLayout()

	def show(self):
		super(OverviewTab, self).show()
		if not self.instance.has_change_listener(self.refresh):
			self.instance.add_change_listener(self.refresh)
		if not self.instance.has_remove_listener(self.on_instance_removed):
			self.instance.add_remove_listener(self.on_instance_removed)

	def hide(self):
		super(OverviewTab, self).hide()
		if self.instance is not None:
			if self.instance.has_change_listener(self.refresh):
				self.instance.remove_change_listener(self.refresh)
			if self.instance.has_remove_listener(self.on_instance_removed):
				self.instance.remove_remove_listener(self.on_instance_removed)

	def on_instance_removed(self):
		self.on_remove()
		self.instance = None



class BranchOfficeOverviewTab(OverviewTab):
	""" the main tab of branch offices and storages """

	def __init__(self, instance):
		super(BranchOfficeOverviewTab, self).__init__(
			widget = 'overview_branchoffice.xml',
			instance = instance
		)
		self.widget.findChild(name="headline").text = unicode(self.instance.settlement.name)
		self.tooltip = _("Branch office overview")
		self._refresh_collector_utilisation()

	def _refresh_collector_utilisation(self):
		utilisation = int(round(self.instance.get_collector_utilisation() * 100))
		self.widget.findChild(name="collector_utilisation").text = unicode(str(utilisation) + '%')

	def refresh(self):
		self.widget.findChild(name="headline").text = unicode(self.instance.settlement.name)
		self._refresh_collector_utilisation()
		super(BranchOfficeOverviewTab, self).refresh()

	def show(self):
		super(BranchOfficeOverviewTab, self).show()
		Scheduler().add_new_object(Callback(self._refresh_collector_utilisation), self, run_in = GAME_SPEED.TICKS_PER_SECOND, loops = -1)

	def hide(self):
		super(BranchOfficeOverviewTab, self).hide()
		Scheduler().rem_all_classinst_calls(self)

	def on_instance_removed(self):
		Scheduler().rem_all_classinst_calls(self)
		super(BranchOfficeOverviewTab, self).on_instance_removed()


class MainSquareOverviewTab(OverviewTab):
	def  __init__(self, instance):
		super(MainSquareOverviewTab, self).__init__(
			widget = 'overview_mainsquare.xml',
			instance = instance
		)
		self.widget.findChild(name="headline").text = unicode(self.instance.settlement.name)
		self.tooltip = _("Main square overview")

	def refresh(self):
		self.widget.findChild(name="headline").text = unicode(self.instance.settlement.name)
		super(MainSquareOverviewTab, self).refresh()


class ShipOverviewTab(OverviewTab):
	def __init__(self, instance, widget = 'overview_ship.xml', \
			icon_path='content/gui/icons/tabwidget/ship/ship_inv_%s.png'):
		super(ShipOverviewTab, self).__init__(instance, widget, icon_path)
		self.tooltip = _("Ship overview")
		health_widget = self.widget.findChild(name='health')
		health_widget.init(self.instance)
		self.add_remove_listener(health_widget.remove)
		weapon_storage_widget = self.widget.findChild(name='weapon_storage')
		weapon_storage_widget.init(self.instance)
		self.add_remove_listener(weapon_storage_widget.remove)

	def refresh(self):
		# show rename when you click on name
		events = {
			'name': Callback(self.instance.session.ingame_gui.show_change_name_dialog, self.instance)
		}

		# check if an island is in range and it doesn't contain a player's settlement
		island_without_player_settlement_found = False
		for island in self.instance.session.world.get_islands_in_radius(self.instance.position, \
		                                                                self.instance.radius):
			player_settlements = [ settlement for settlement in island.settlements if \
			                       settlement.owner is self.instance.session.world.player ]
			if len(player_settlements) == 0:
				island_without_player_settlement_found = True

		if island_without_player_settlement_found:
			events['foundSettlement'] = Callback(self.instance.session.ingame_gui._build, \
			                                     BUILDINGS.BRANCH_OFFICE_CLASS, \
			                                     weakref.ref(self.instance) )
			self.widget.child_finder('bg_button').set_active()
			self.widget.child_finder('foundSettlement').set_active()
		else:
			events['foundSettlement'] = None
			self.widget.child_finder('bg_button').set_inactive()
			self.widget.child_finder('foundSettlement').set_inactive()

		cb = Callback( self.instance.session.ingame_gui.resourceinfo_set,
		   self.instance,
		   Entities.buildings[BUILDINGS.BRANCH_OFFICE_CLASS].costs,
		   {},
		   res_from_ship = True )
		events['foundSettlement/mouseEntered'] = cb
		cb = Callback( self.instance.session.ingame_gui.resourceinfo_set,
		   None ) # hides the resource status widget
		events['foundSettlement/mouseExited'] = cb
		self.widget.mapEvents(events)
		super(ShipOverviewTab, self).refresh()


class FightingShipOverviewTab(ShipOverviewTab):
	def __init__(self, instance, widget = 'overview_ship.xml'):
		super(FightingShipOverviewTab, self).__init__(instance, widget)
		stance_widget = StanceWidget()
		stance_widget.init(self.instance)
		self.add_remove_listener(stance_widget.remove)
		self.widget.findChild(name='stance').addChild(stance_widget)

	def show(self):
		self.widget.findChild(name='weapon_storage').update()
		super(FightingShipOverviewTab, self).show()

class TraderShipOverviewTab(OverviewTab):
	def __init__(self, instance):
		super(TraderShipOverviewTab, self).__init__(
			widget = 'overview_tradership.xml',
			icon_path='content/gui/icons/tabwidget/ship/ship_inv_%s.png',
			instance = instance
		)
		self.tooltip = _("Ship overview")

class GroundUnitOverviewTab(OverviewTab):
	def __init__(self, instance):
		super(GroundUnitOverviewTab, self).__init__(
			widget = 'overview_groundunit.xml',
			instance = instance)
		self.tooltip = _("Unit overview")
		health_widget = self.widget.findChild(name='health')
		health_widget.init(self.instance)
		self.add_remove_listener(health_widget.remove)
		weapon_storage_widget = self.widget.findChild(name='weapon_storage')
		weapon_storage_widget.init(self.instance)
		self.add_remove_listener(weapon_storage_widget.remove)
		stance_widget = self.widget.findChild(name='stance')
		stance_widget.init(self.instance)
		self.add_remove_listener(stance_widget.remove)

class ProductionOverviewTab(OverviewTab):
	production_line_gui_xml = "overview_productionline.xml"

	def  __init__(self, instance):
		super(ProductionOverviewTab, self).__init__(
			widget = 'overview_productionbuilding.xml',
			instance = instance
		)
		self.tooltip = _("Production overview")

		self.destruct_button = DeleteButton(name="destruct_button", \
		                                    tooltip=_("Destroy building"), \
		                                    position=(190,330) )
		self.widget.addChild(self.destruct_button)
		self.widget.mapEvents( { 'destruct_button' : self.destruct_building } )

	def refresh(self):
		"""This function is called by the TabWidget to redraw the widget."""
		self._refresh_utilisation()

		# remove old production line data
		parent_container = self.widget.child_finder('production_lines')
		while len(parent_container.children) > 0:
			parent_container.removeChild(parent_container.children[0])

		# create a container for each production
		# sort by production line id to have a consistent (basically arbitrary) order
		for production in sorted(self.instance._get_productions(), \
								             key=(lambda x: x.get_production_line_id())):
			gui = load_uh_widget(self.production_line_gui_xml)
			# fill in values to gui reflecting the current game state
			container = gui.findChild(name="production_line_container")
			if production.is_paused():
				container.removeChild( container.findChild(name="toggle_active_active") )
				container.findChild(name="toggle_active_inactive").name = "toggle_active"
			else:
				container.removeChild( container.findChild(name="toggle_active_inactive") )
				container.findChild(name="toggle_active_active").name = "toggle_active"

			# fill it with input and output resources
			in_res_container = container.findChild(name="input_res")
			for in_res in production.get_consumed_resources():
				filled = float(self.instance.inventory[in_res]) * 100 / \
				       self.instance.inventory.get_limit(in_res)
				in_res_container.addChild( \
				  ImageFillStatusButton.init_for_res(self.instance.session.db,\
				                                     in_res, \
				                                     self.instance.inventory[in_res], \
				                                     filled, \
				                                     use_inactive_icon=False, \
				                                     uncached=True) \
				)
			out_res_container = container.findChild(name="output_res")
			for out_res in production.get_produced_res():
				filled = float(self.instance.inventory[out_res]) * 100 /  \
				       self.instance.inventory.get_limit(out_res)
				out_res_container.addChild( \
				  ImageFillStatusButton.init_for_res(self.instance.session.db, \
				                                     out_res, \
				                                     self.instance.inventory[out_res], \
				                                     filled, \
				                                     use_inactive_icon=False, \
				                                     uncached=True) \
				)


			# fix pychans lack of dynamic container sizing
			# the container in the xml must provide a height attribute, that is valid for
			# one resource.
			max_res_in_one_line = max(len(production.get_produced_res()), \
			                          len(production.get_consumed_resources()))
			container.height = max_res_in_one_line * container.height


			# active toggle_active button
			container.mapEvents( \
			  { 'toggle_active': \
			    Callback(ToggleActive(self.instance, production).execute, self.instance.session) \
			    } )
			# NOTE: this command causes a refresh, so we needn't change the toggle_active-button-image
			container.stylize('menu_black')
			parent_container.addChild(container)
		super(ProductionOverviewTab, self).refresh()

	def destruct_building(self):
		self.instance.session.ingame_gui.hide_menu()
		if self.destruct_button.gui.isVisible():
			self.destruct_button.hide_tooltip()
		Tear(self.instance).execute(self.instance.session)

	def _refresh_utilisation(self):
		utilisation = 0
		if hasattr(self.instance, 'capacity_utilisation'):
			utilisation = int(round(self.instance.capacity_utilisation * 100))
		self.widget.child_finder('capacity_utilisation').text = unicode(str(utilisation) + '%')

	def show(self):
		super(ProductionOverviewTab, self).show()
		Scheduler().add_new_object(Callback(self._refresh_utilisation), self, run_in = GAME_SPEED.TICKS_PER_SECOND, loops = -1)

	def hide(self):
		super(ProductionOverviewTab, self).hide()
		Scheduler().rem_all_classinst_calls(self)

	def on_instance_removed(self):
		Scheduler().rem_all_classinst_calls(self)
		super(ProductionOverviewTab, self).on_instance_removed()

class SettlerOverviewTab(OverviewTab):
	def  __init__(self, instance):
		super(SettlerOverviewTab, self).__init__(
			widget = 'overview_settler.xml',
			instance = instance
		)
		self.tooltip = _("Settler overview")
		self.widget.findChild(name="headline").text = unicode(self.instance.settlement.name)
		_setup_tax_slider(self.widget.child_finder('tax_slider'), self.widget.child_finder('tax_val_label'), self.instance)

		self.widget.child_finder('tax_val_label').text = unicode(self.instance.settlement.tax_settings[self.instance.level])
		action_set = ActionSetLoader.get_action_sets()[self.instance._action_set_id]
		action_gfx = action_set.items()[0][1]
		image = action_gfx[45].keys()[0]
		self.widget.findChild(name="building_image").image = image

	def refresh(self):
		self.widget.child_finder('happiness').progress = self.instance.happiness
		self.widget.child_finder('inhabitants').text = unicode( "%s/%s" % ( \
			self.instance.inhabitants, self.instance.inhabitants_max ) )
		self.widget.child_finder('taxes').text = unicode(self.instance.last_tax_payed)
		self.update_consumed_res()
		self.widget.findChild(name="headline").text = unicode(self.instance.settlement.name)
		super(SettlerOverviewTab, self).refresh()

	def update_consumed_res(self):
		"""Updates the container that displays the needed resources of the settler"""
		container = self.widget.findChild(name="needed_res")
		# remove icons from the container
		container.removeChildren(*container.children)

		# create new ones
		resources = self.instance.get_currently_not_consumed_resources()
		for res in resources:
			icon = create_resource_icon(res, self.instance.session.db)
			container.addChild(icon)

		container.adaptLayout()

class SignalFireOverviewTab(OverviewTab):
	def __init__(self, instance):
		super(SignalFireOverviewTab, self).__init__(
			widget = 'overview_signalfire.xml',
			instance = instance
		)
		action_set = ActionSetLoader.get_action_sets()[self.instance._action_set_id]
		action_gfx = action_set.items()[0][1]
		image = action_gfx[45].keys()[0]
		self.widget.findChild(name="building_image").image = image
		self.tooltip = _("Overview")

class EnemyBuildingOverviewTab(OverviewTab):
	def  __init__(self, instance):
		super(EnemyBuildingOverviewTab, self).__init__(
			widget = 'overview_enemybuilding.xml',
			instance = instance
		)
		self.widget.findChild(name="headline").text = unicode(self.instance.owner.name)

class EnemyBranchOfficeOverviewTab(OverviewTab):
	def __init__(self, instance):
		super(EnemyBranchOfficeOverviewTab, self).__init__(
			widget = 'overview_enemybranchoffice.xml',
			instance = instance
		)
		self.widget.findChild(name="headline").text = unicode(self.instance.settlement.name)
		self.tooltip = _("Branch office overview")

	def refresh(self):
		self.widget.findChild(name="headline").text = unicode(self.instance.settlement.name)

		selling_inventory = self.widget.findChild(name='selling_inventory')
		selling_inventory.init(self.instance.session.db, self.instance.settlement.inventory, self.instance.settlement.sell_list, True)

		buying_inventory = self.widget.findChild(name='buying_inventory')
		buying_inventory.init(self.instance.session.db, self.instance.settlement.inventory, self.instance.settlement.buy_list, False)

		super(EnemyBranchOfficeOverviewTab, self).refresh()

class EnemyShipOverviewTab(OverviewTab):
	def  __init__(self, instance):
		super(EnemyShipOverviewTab, self).__init__(
			widget = 'overview_enemyunit.xml',
			icon_path='content/gui/icons/tabwidget/ship/ship_inv_%s.png',
			instance = instance
		)
		self.widget.findChild(name="headline").text = unicode(self.instance.owner.name)

class ResourceDepositOverviewTab(OverviewTab):
	def  __init__(self, instance):
		super(ResourceDepositOverviewTab, self).__init__(
			widget = 'overview_resourcedeposit.xml',
			instance = instance
		)
		self.widget.child_finder("inventory").init(self.instance.session.db, \
		                                           self.instance.inventory)

	def refresh(self):
		super(ResourceDepositOverviewTab, self).refresh()
		self.widget.child_finder("inventory").update()


###
# Minor utility functions

def _setup_tax_slider(slider, val_label, building):
	"""Set up a slider to work as tax slider"""
	slider.setScaleStart(SETTLER.TAX_SETTINGS_MIN)
	slider.setScaleEnd(SETTLER.TAX_SETTINGS_MAX)
	slider.setStepLength(SETTLER.TAX_SETTINGS_STEP)
	slider.setValue(building.settlement.tax_settings[building.level])
	slider.stylize('book')
	def on_slider_change():
		val_label.text = unicode(slider.getValue())
		if(building.settlement.tax_settings[building.level] != slider.getValue()):
			SetTaxSetting(building.settlement, building.level, slider.getValue()).execute(building.settlement.session)
	slider.capture(on_slider_change)
