# -*- coding: utf-8 -*-
# ###################################################
# Copyright (C) 2009 The Unknown Horizons Team
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

import math
import logging
import copy

from horizons.util import WorldObject
from horizons.constants import PRODUCTION_STATES
from horizons.world.production.productionline import ProductionLine

import horizons.main

class Production(WorldObject):
	"""Class for production to be used by ResourceHandler.
	Controls production and starts it by watching the assigned building's inventory,
	which is virtually the only "interface" to the building.
	This ensures independence and encapsulation from the building code.

	A Production is active by default, but you can pause it.

	Before we can start production, we check certain assertions, i.e. if we have all the
	resources, that the production takes and if there is enough space to store the produced goods.

	It has basic states, which are useful for e.g. setting animation. Changes in state
	can be observed via ChangeListener interface."""
	log = logging.getLogger('world.production')


	## INIT/DESTRUCT
	def __init__(self, inventory, prod_line_id, **kwargs):
		super(Production, self).__init__(**kwargs)
		self.__init(inventory, prod_line_id, PRODUCTION_STATES.waiting_for_res)
		self.inventory.add_change_listener(self._check_inventory, call_listener_now=True)

	def __init(self, inventory, prod_line_id, state, pause_old_state = None):
		"""
		@param inventory: inventory of assigned building
		@param prod_line_id: id of production line.
		"""
		self.inventory = inventory
		self._state = state
		self._pause_remaining_ticks = None # only used in pause()
		self._pause_old_state = pause_old_state # only used in pause()

		self._prod_line = self._create_production_line(prod_line_id)

	@classmethod
	def _create_production_line(self, prod_line_id):
		"""Returns a non-changeable production line instance"""
		if not prod_line_id in ProductionLine.data:
			ProductionLine.load_data(prod_line_id)
		return ProductionLine.data[prod_line_id]

	def save(self, db):
		remaining_ticks = None
		if self._state == PRODUCTION_STATES.paused:
			remaining_ticks = self._pause_remaining_ticks
		elif self._state == PRODUCTION_STATES.producing:
			remaining_ticks = \
						horizons.main.session.scheduler.get_remaining_ticks(self, self._finished_producing)
		db('INSERT INTO production(rowid, state, prod_line_id, remaining_ticks, \
		_pause_old_state) VALUES(?, ?, ?, ?, ?)', self.getId(), self._state.index, \
												self._prod_line.id, remaining_ticks, \
												None if self._pause_old_state is None else self._pause_old_state.index)

	@classmethod
	def load(cls, db, worldid):
		self = cls.__new__(cls)

		db_data = db('SELECT state, owner, prod_line_id, remaining_ticks, _pause_old_state \
								  FROM production WHERE rowid = ?', worldid)[0]
		self.__init(WorldObject.get_object_by_id(db_data[1]).inventory, db_data[2], \
								PRODUCTION_STATES[db_data[0]], None if db_data[4] is None else PRODUCTION_STATES[db_data[4]])
		if self._state == PRODUCTION_STATES.paused:
			self._pause_remaining_ticks = db_data[3]
		elif self._state == PRODUCTION_STATES.producing:
			horizons.main.session.scheduler.add_new_object(self._finished_producing, self, db_data[3])
		elif self._state == PRODUCTION_STATES.waiting_for_res:
			self.inventory.add_change_listener(self._check_inventory)

		super(cls, self).load(db, worldid)
		return self

	def remove(self):
		horizons.main.session.scheduler.rem_all_classinst_calls(self)
		super(Production, self).remove()

	## INTERFACE METHODS
	def get_production_line_id(self):
		"""Returns id of production line"""
		return self._prod_line.id

	def get_consumed_resources(self):
		"""Res that are consumed here. Returns dict {res:amount}. Interface for _prod_line."""
		return self._prod_line.consumed_res

	def get_produced_res(self):
		"""Res that are produced here. Returns dict {res:amount}. Interface for _prod_line."""
		return self._prod_line.produced_res

	def changes_animation(self):
		"""Returns wether the production should change the animation"""
		return self._prod_line.changes_animation

	def get_state(self):
		"""Returns the Production's current state"""
		return self._state

	def get_animating_state(self):
		"""Returns the production's current state,
		but only if it effects the animation, else None"""
		if self._prod_line.changes_animation:
			return self._state
		else:
			return None

	def toggle_pause(self):
		if self.is_paused():
			self.pause()
		else:
			self.pause(pause=False)

	def is_paused(self):
		return self._state == PRODUCTION_STATES.paused

	def pause(self, pause = True):
		self.log.debug("Production pause: %s", pause)
		if not pause: # do unpause
			if self._pause_old_state == PRODUCTION_STATES.waiting_for_res:
				# just restore watching
				self.inventory.add_change_listener(self._check_inventory, call_listener_now=True)
			elif self._pause_old_state == PRODUCTION_STATES.producing:
				# restore scheduler call
				horizons.main.session.scheduler.add_new_object(self._finished_producing, self, \
					 self._pause_remaining_ticks)
			else:
				assert False

			# switch state
			self._state = self._pause_old_state
			self._pause_old_state = None

		else: # do pause
			if self._state == PRODUCTION_STATES.waiting_for_res:
				# just stop watching for new res
				self.inventory.remove_change_listener(self._check_inventory)
			elif self._state == PRODUCTION_STATES.producing:
				# save when production finishes and remove that call
				self._pause_remaining_ticks = \
						horizons.main.session.scheduler.get_remaining_ticks(self, self._finished_producing)
				horizons.main.session.scheduler.rem_call(self, self._finished_producing)
			else:
				assert False

			# switch state
			self._pause_old_state = self._state
			self._state = PRODUCTION_STATES.paused

		self._changed()

	def finish_production_now(self):
		"""Makes the production finish now"""
		if self._state != PRODUCTION_STATES.producing:
			return
		horizons.main.session.scheduler.rem_call(self, self._finished_producing)
		self._finished_producing()

	def alter_production_time(self, modifier):
		"""@see ProductionLine.alter_production_time"""
		self._prod_line.alter_production_time(modifier)

	## PROTECTED METHODS
	def _check_inventory(self):
		"""Called when assigned building's inventory changed in some way"""
		assert self._state in (PRODUCTION_STATES.waiting_for_res, \
													 PRODUCTION_STATES.inventory_full) or True
		check_space = self._check_for_space_for_produced_res()
		if not check_space:
			# can't produce, no space in our inventory
			self._state = PRODUCTION_STATES.inventory_full
			self._changed()
		elif self._check_available_res():
			# we have space in our inventory and needed res are available
			# stop listening for res
			self.inventory.remove_change_listener(self._check_inventory)
			self._start_production()
		else:
			# we have space in our inventory, but needed res are missing
			self._state = PRODUCTION_STATES.waiting_for_res
			self._changed()

	def _start_production(self):
		"""Acctually start production. Sets self to producing state"""
		self._state = PRODUCTION_STATES.producing
		self._produce()
		self._changed()

	def _produce(self):
		"""Called when there are enough res in the inventory for starting production"""
		self.log.debug("Production start")
		assert self._check_available_res() and self._check_for_space_for_produced_res()
		# take the res we need
		self._remove_res_to_expend()
		# call finished in some time
		time = int(round( horizons.main.session.timer.get_ticks(self._prod_line.time) ))
		horizons.main.session.scheduler.add_new_object(self._finished_producing, self, time)

	def _finished_producing(self):
		"""Called when the production finishes."""
		self.log.debug("%s finished", self)
		self._give_produced_res()
		self.inventory.add_change_listener(self._check_inventory, call_listener_now=True)

	def _give_produced_res(self):
		"""Put produces goods to the inventory"""
		for res, amount in self._prod_line.produced_res.iteritems():
			self.inventory.alter(res, amount)
			self.log.debug("produced %s of %s", amount, res)

	def _check_available_res(self):
		"""Checks if there are enough resources to start production.
		@return: bool, true if we can start production
		"""
		for res, amount in self._prod_line.consumed_res.iteritems():
			if self.inventory[res] < (-amount): # consumed res have negative sign
				return False
		return True

	def _remove_res_to_expend(self):
		"""Removes the resources from the inventory, that production takes."""
		for res, amount in self._prod_line.consumed_res.iteritems():
			remnant = self.inventory.alter(res, amount)
			assert remnant == 0

	def _check_for_space_for_produced_res(self):
		"""Checks if there is enough space in the inventory for the res, we want to produce.
		@return bool, true if everything can fit."""
		for res, amount in self._prod_line.produced_res.iteritems():
			if self.inventory.get_free_space_for(res) < amount:
				return False
		return True

	def __str__(self): # debug
		return 'Production(state=%s;prodline=%s)' % (self._state, self._prod_line)


class ChangingProduction(Production):
	"""Same as Production, but changes properties of the production line"""
	def _create_production_line(self, prod_line_id):
		"""Returns a changeable production line instance"""
		return ProductionLine(prod_line_id)

class SettlerProduction(ChangingProduction):
	"""For settlers, production behavies different:
	They produce happiness from the goods they get. They get happy immediately when the get
	the resource (i.e. they produce at production start)"""
	def _give_produced_res(self):
		pass # don't give any resources, when they acctually should be given

	def _remove_res_to_expend(self):
		super(SettlerProduction, self)._remove_res_to_expend()
		# give the resources when taking away the consumed goods at prod start
		super(SettlerProduction, self)._give_produced_res()

class ProgressProduction(Production):
	"""Same as Production, but starts as soon as any needed res is available (doesn't wait
	until all of them are ready)

	Implementation:
	When res are available, they are removed from the production line. The prod line is
	reloaded on a new production."""

	## INIT/DESTRUCT
	def __init__(self, *args, **kwargs):
		super(ProgressProduction, self).__init__(*args, **kwargs)
		self.__init()

	def __init(self, progress = 0):
		self.original_prod_line = copy.deepcopy(self._prod_line)
		self.progress = progress # float indicating current production progress

	def save(self, db):
		# TODO
		pass

	def load(self, db, worldid):
		super(ProgressProduction, self).load(db, worldid)
		self.__init()
		# TODO

	## PROTECTED METHODS
	def _check_available_res(self):
		for res in self._prod_line.consumed_res.iterkeys():
			if self.inventory[res] > 0:
				return True
		return False

	def _remove_res_to_expend(self):
		"""Takes as many res as there are and returns sum of amount of res taken."""
		taken = 0
		for res, amount in self._prod_line.consumed_res.iteritems():
			remnant = self.inventory.alter(res, amount) # try to get all
			self._prod_line.alter_amount(res, remnant) # set how much we still need to get
			taken += math.abs(remnant) + amount
		return taken

	def _produce(self):
		# check if we're done
		still_needed_res = sum(self._prod_line.consumed_res.itervalues())
		if still_needed_res == 0:
			self._finished_producing()
			return

		removed_res = self._remove_res_to_expend()
		# check if there were res
		if removed_res == 0:
			# watch inventory for new res
			self.inventory.add_change_listener(self._check_inventory, call_listener_now=True)
			self._state = PRODUCTION_STATES.waiting_for_res
			self._changed()
			return

		# calculate how much of the whole production process we can produce now
		# and set the scheduler waiting time accordingly (e.g. half of res => wait half of prod time)
		all_needed_res = sum(self.original_prod_line.consumed_res.itervalues())
		part_of_whole_production = float(removed_res) / all_needed_res
		prod_time = int(round(horizons.main.session.timer.get_ticks( part_of_whole_production * self._prod_line.time )))
		prod_time = min(prod_time, 1) # wait at least 1 tick
		# do part of production and call this again when done
		horizons.main.session.scheduler.add_new_object(self._produce, self, prod_time)

		# set new progress
		self.progress += part_of_whole_production

	def _finished_producing(self):
		super(ProgressProduction, self)._finished_producing()
		self.progress = 0
		# reset prodline
		self._prod_line = copy.copy(self.original_prod_line)