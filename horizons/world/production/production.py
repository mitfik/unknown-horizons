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

import math
import logging
import copy

from collections import defaultdict, deque

from horizons.util import WorldObject
from horizons.util.changelistener import metaChangeListenerDecorator
from horizons.constants import PRODUCTION, GAME_SPEED
from horizons.world.production.productionline import ProductionLine

from horizons.scheduler import Scheduler


@metaChangeListenerDecorator("production_finished")
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
	def __init__(self, inventory, prod_line_id, auto_start=True, **kwargs):
		super(Production, self).__init__(**kwargs)
		self._state_history = deque()
		self.__init(inventory, prod_line_id, PRODUCTION.STATES.none, Scheduler().cur_tick)
		if auto_start:
			self.inventory.add_change_listener(self._check_inventory, call_listener_now=True)
		else:
			self.inventory.add_change_listener(self._check_inventory, call_listener_now=False)

	def __init(self, inventory, prod_line_id, state, creation_tick, pause_old_state = None):
		"""
		@param inventory: inventory of assigned building
		@param prod_line_id: id of production line.
		"""
		self.inventory = inventory
		self._state = state
		self._pause_remaining_ticks = None # only used in pause()
		self._pause_old_state = pause_old_state # only used in pause()
		self._creation_tick = creation_tick

		assert isinstance(prod_line_id, int)
		self._prod_line = self._create_production_line(prod_line_id)

	@classmethod
	def _create_production_line(self, prod_line_id):
		"""Returns a non-changeable production line instance"""
		try:
			return ProductionLine.data[prod_line_id]
		except KeyError:
			ProductionLine.load_data(prod_line_id)
			return ProductionLine.data[prod_line_id]

	def save(self, db):
		self._clean_state_history()
		current_tick = Scheduler().cur_tick
		translated_creation_tick = self._creation_tick - current_tick + 1 #  pre-translate the tick number for the loading process

		remaining_ticks = None
		if self._state == PRODUCTION.STATES.paused:
			remaining_ticks = self._pause_remaining_ticks
		elif self._state == PRODUCTION.STATES.producing:
			remaining_ticks = Scheduler().get_remaining_ticks(self, self._finished_producing)
		# use a number > 0 for ticks
		if remaining_ticks < 1:
			remaining_ticks = 1
		db('INSERT INTO production(rowid, state, prod_line_id, remaining_ticks, _pause_old_state, creation_tick) VALUES(?, ?, ?, ?, ?, ?)', \
			self.worldid, self._state.index, self._prod_line.id, remaining_ticks, \
			None if self._pause_old_state is None else self._pause_old_state.index, translated_creation_tick)

		# save state history
		for tick, state in self._state_history:
			 # pre-translate the tick number for the loading process
			translated_tick = tick - current_tick + 1
			db("INSERT INTO production_state_history(production, tick, state) VALUES(?, ?, ?)", \
				self.worldid, translated_tick, state)

	@classmethod
	def load(cls, db, worldid):
		self = cls.__new__(cls)
		self._load(db, worldid)
		return self

	def _load(self, db, worldid):
		super(Production, self).load(db, worldid)

		db_data = db.get_production_row(worldid)
		self.__init(WorldObject.get_object_by_id(db_data[1]).inventory, db_data[2], PRODUCTION.STATES[db_data[0]], \
			db_data[5], None if db_data[4] is None else PRODUCTION.STATES[db_data[4]])
		if self._state == PRODUCTION.STATES.paused:
			self._pause_remaining_ticks = db_data[3]
		elif self._state == PRODUCTION.STATES.producing:
			Scheduler().add_new_object(self._finished_producing, self, db_data[3])
		elif self._state == PRODUCTION.STATES.waiting_for_res or \
		     self._state == PRODUCTION.STATES.inventory_full:
			self.inventory.add_change_listener(self._check_inventory)

		self._state_history = db.get_production_state_history(worldid)

	def remove(self):
		# depending on state, a check_inventory listener might be active
		self.inventory.discard_change_listener(self._check_inventory)
		Scheduler().rem_all_classinst_calls(self)
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

	def get_production_time(self):
		return self._prod_line.time

	def get_produced_units(self):
		"""@return dict of produced units {unit_id: amount}"""
		return self._prod_line.unit_production

	def changes_animation(self):
		"""Returns whether the production should change the animation"""
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
		return self._state == PRODUCTION.STATES.paused

	def pause(self, pause = True):
		self.log.debug("Production pause: %s", pause)
		if not pause: # do unpause
			# switch state
			self._state = self._pause_old_state
			self._pause_old_state = None

			# apply state
			if self._state in (PRODUCTION.STATES.waiting_for_res, \
			                   PRODUCTION.STATES.inventory_full):
				# just restore watching
				self.inventory.add_change_listener(self._check_inventory, call_listener_now=True)
			elif self._state == PRODUCTION.STATES.producing:
				# restore scheduler call
				Scheduler().add_new_object(self._finished_producing, self, \
				                           self._pause_remaining_ticks)
			else:
				assert False, 'Unhandled production state: %s' % self._pause_old_state
		else: # do pause
			# switch state
			self._pause_old_state = self._state
			self._state = PRODUCTION.STATES.paused

			if self._pause_old_state in (PRODUCTION.STATES.waiting_for_res, \
			                   PRODUCTION.STATES.inventory_full):
				# just stop watching for new res
				self.inventory.discard_change_listener(self._check_inventory)
			elif self._pause_old_state == PRODUCTION.STATES.producing:
				# save when production finishes and remove that call
				self._pause_remaining_ticks = \
						Scheduler().get_remaining_ticks(self, self._finished_producing)
				Scheduler().rem_call(self, self._finished_producing)
			else:
				assert False, 'Unhandled production state: %s' % self._state

		self._changed()

	def finish_production_now(self):
		"""Makes the production finish now"""
		if self._state != PRODUCTION.STATES.producing:
			return
		Scheduler().rem_call(self, self._finished_producing)
		self._finished_producing()

	def alter_production_time(self, modifier):
		"""@see ProductionLine.alter_production_time"""
		try:
			self._prod_line.alter_production_time(modifier)
		except AttributeError: # production line doesn't have this alter method
			pass

	def get_state_history_length(self):
		return min(PRODUCTION.STATISTICAL_WINDOW, Scheduler().cur_tick - self._creation_tick)

	def get_state_history_times(self, ignore_pause):
		"""
		Returns the part of time 0 <= x <= 1 the production has been in a state during the last history_length ticks.
		"""

		self._clean_state_history()
		result = defaultdict(lambda: 0)
		current_tick = Scheduler().cur_tick
		pause_state = PRODUCTION.STATES.paused.index
		first_relevant_tick = self._get_first_relevant_tick(ignore_pause)
		num_entries = len(self._state_history)

		for i in xrange(num_entries):
			if ignore_pause and self._state_history[i][1] == pause_state:
				continue
			tick = self._state_history[i][0]
			if tick >= current_tick:
				break

			next_tick = min(self._state_history[i + 1][0], current_tick) if i + 1 < num_entries else current_tick
			if next_tick <= first_relevant_tick:
				continue
			relevant_ticks = next_tick - tick
			if tick < first_relevant_tick:
				# the beginning is not relevant
				relevant_ticks -= first_relevant_tick - tick
			result[self._state_history[i][1]] += relevant_ticks

		total_length = sum(result.itervalues())
		if total_length == 0:
			return result
		for key in result:
			result[key] /= float(total_length)
		return result

	def get_age(self):
		return Scheduler().cur_tick - self._creation_tick

	## PROTECTED METHODS
	def _get_first_relevant_tick(self, ignore_pause):
		"""
		Returns the first tick that is relevant for production utilisation calculation
		@param ignore_pause: whether to ignore the time spent in the pause state
		"""

		current_tick = Scheduler().cur_tick
		first_relevant_tick = current_tick - self.get_state_history_length()
		if not ignore_pause:
			return first_relevant_tick

		# ignore paused time
		pause_state = PRODUCTION.STATES.paused.index
		for i in xrange(len(self._state_history) - 1, -1, -1):
			if self._state_history[i][1] != pause_state:
				continue
			tick = self._state_history[i][0]
			next_tick = self._state_history[i + 1][0] if i + 1 < len(self._state_history) else current_tick
			if next_tick <= first_relevant_tick:
				break
			first_relevant_tick -= next_tick - tick
		return max(self._creation_tick, first_relevant_tick)

	def _clean_state_history(self):
		""" remove the part of the state history that is too old to matter """
		first_relevant_tick = self._get_first_relevant_tick(True)
		while len(self._state_history) > 1 and self._state_history[1][0] < first_relevant_tick:
			self._state_history.popleft()

	def _changed(self):
		super(Production, self)._changed()
		if not self._prod_line.save_statistics:
			return

		state = self._state.index
		current_tick = Scheduler().cur_tick

		if self._state_history and self._state_history[-1][0] == current_tick:
			self._state_history.pop() # make sure no two events are on the same tick
		if not self._state_history or self._state_history[-1][1] != state:
			self._state_history.append((current_tick, state))

		self._clean_state_history()

	def _check_inventory(self):
		"""Called when assigned building's inventory changed in some way"""
		check_space = self._check_for_space_for_produced_res()
		if not check_space:
			# can't produce, no space in our inventory
			self._state = PRODUCTION.STATES.inventory_full
			self._changed()
		elif self._check_available_res():
			# we have space in our inventory and needed res are available
			# stop listening for res
			self.inventory.remove_change_listener(self._check_inventory)
			self._start_production()
		else:
			# we have space in our inventory, but needed res are missing
			self._state = PRODUCTION.STATES.waiting_for_res
			self._changed()

	def _start_production(self):
		"""Actually start production. Sets self to producing state"""
		self._state = PRODUCTION.STATES.producing
		self._produce()
		self._changed()

	def _produce(self):
		"""Called when there are enough res in the inventory for starting production"""
		self.log.debug("%s start", self)
		assert self._check_available_res() and self._check_for_space_for_produced_res()
		# take the res we need
		self._remove_res_to_expend()
		# call finished in some time
		time = Scheduler().get_ticks(self._prod_line.time)
		Scheduler().add_new_object(self._finished_producing, self, time)

	def _finished_producing(self, continue_producing=True, **kwargs):
		"""Called when the production finishes."""
		self.log.debug("%s finished", self)
		self._give_produced_res()
		self.on_production_finished()
		if continue_producing:
			self.state = PRODUCTION.STATES.waiting_for_res
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
	"""Same as Production, but can changes properties of the production line"""
	def _create_production_line(self, prod_line_id):
		"""Returns a changeable production line instance"""
		return ProductionLine(prod_line_id)

class SettlerProduction(ChangingProduction):
	"""For settlers, production behaves different:
	They produce happiness from the goods they get. They get happy immediately when the get
	the resource (i.e. they produce at production start)"""
	def _give_produced_res(self):
		pass # don't give any resources, when they actually should be given

	def _remove_res_to_expend(self):
		super(SettlerProduction, self)._remove_res_to_expend()
		# give the resources when taking away the consumed goods at prod start
		super(SettlerProduction, self)._give_produced_res()

class SingleUseProduction(Production):
	"""This Production just produces one time, and then finishes.
	Notification of the finishing is done via production_finished listeners.
	Use case: Settler getting upgrade material"""
	def __init__(self, inventory, prod_line_id, **kwargs):
		super(SingleUseProduction, self).__init__(inventory=inventory, prod_line_id=prod_line_id, **kwargs)

	def _finished_producing(self, **kwargs):
		super(SingleUseProduction, self)._finished_producing(continue_producing=False, **kwargs)
		self.state = PRODUCTION.STATES.done

class ProgressProduction(Production):
	"""Same as Production, but starts as soon as any needed res is available (doesn't wait
	until all of them are ready)

	Implementation:
	When res are available, they are removed from the production line. The prod line is
	reloaded on a new production."""

	## INIT/DESTRUCT
	def __init__(self, **kwargs):
		super(ProgressProduction, self).__init__(**kwargs)
		self.__init()

	def __init(self, progress = 0):
		self.original_prod_line = copy.deepcopy(self._prod_line)
		self.progress = progress # float indicating current production progress

	def save(self, db):
		# TODO
		pass

	def _load(self, db, worldid):
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
			self._prod_line.change_amount(res, remnant) # set how much we still need to get
			taken += abs(remnant) + amount
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
			self.inventory.add_change_listener(self._check_inventory)
			self._state = PRODUCTION.STATES.waiting_for_res
			self._changed()
			return

		# calculate how much of the whole production process we can produce now
		# and set the scheduler waiting time accordingly (e.g. half of res => wait half of prod time)
		all_needed_res = sum(self.original_prod_line.consumed_res.itervalues())
		part_of_whole_production = float(removed_res) / all_needed_res
		prod_time = Scheduler().get_ticks( part_of_whole_production * self._prod_line.time )
		prod_time = min(prod_time, 1) # wait at least 1 tick
		# do part of production and call this again when done
		Scheduler().add_new_object(self._produce, self, prod_time)

		# set new progress
		self.progress += part_of_whole_production

	def _finished_producing(self, **kwargs):
		super(ProgressProduction, self)._finished_producing(**kwargs)
		self.progress = 0
		# reset prodline
		self._prod_line = copy.copy(self.original_prod_line)

class SingleUseProgressProduction(ProgressProduction, SingleUseProduction):
	"""A production that needs to have a progress and also is only used one time."""

	def __init__(self, **kwargs):
		super(SingleUseProgressProduction, self).__init__(**kwargs)

	def _finished_producing(self, **kwargs):
		super(SingleUseProgressProduction, self)._finished_producing(**kwargs)
