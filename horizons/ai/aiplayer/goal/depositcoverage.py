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

from horizons.ai.aiplayer.goal.settlementgoal import SettlementGoal
from horizons.ai.aiplayer.constants import BUILD_RESULT, BUILDING_PURPOSE
from horizons.constants import BUILDINGS
from horizons.util.python import decorators
from horizons.constants import BUILDINGS

class DepositCoverageGoal(SettlementGoal):
	"""Build storage tents to get a resource deposit inside the settlement."""

	@property
	def deposit_class(self):
		"""Return the building class id of the deposit."""
		raise NotImplementedError, 'This function has to be overridden.'

	def _have_reachable_deposit(self, building_id):
		"""Returns true if there is a resource deposit outside the settlement that is not owned by another player."""
		for building in self.land_manager.resource_deposits[building_id]:
			if building.settlement is None:
				return True
		return False

	@property
	def active(self):
		return super(DepositCoverageGoal, self).active and not self.production_builder.have_deposit(self.deposit_class) and \
			self._have_reachable_deposit(self.deposit_class)

	def _improve_deposit_coverage(self):
		"""Get closer to having a resource deposit in the settlement."""
		if not self.production_builder.have_resources(BUILDINGS.STORAGE_CLASS):
			return BUILD_RESULT.NEED_RESOURCES

		available_deposits = []
		for building in self.land_manager.resource_deposits[self.deposit_class]:
			if building.settlement is None:
				available_deposits.append(building)
		if not available_deposits:
			return BUILD_RESULT.IMPOSSIBLE

		options = []
		for x, y in self.production_builder.plan:
			builder = self.production_builder.make_builder(BUILDINGS.STORAGE_CLASS, x, y, False)
			if not builder:
				continue

			min_distance = None
			for building in available_deposits:
				distance = building.position.distance(builder.position)
				if min_distance is None or min_distance > distance:
					min_distance = distance

			alignment = 0
			for tile in self.production_builder.iter_neighbour_tiles(builder.position):
				if tile is None:
					continue
				coords = (tile.x, tile.y)
				if coords not in self.production_builder.plan or self.production_builder.plan[coords][0] != BUILDING_PURPOSE.NONE:
					alignment += 1

			value = min_distance - alignment * self.personality.alignment_coefficient
			options.append((-value, builder))

		return self.production_builder.build_best_option(options, BUILDING_PURPOSE.STORAGE)

	def execute(self):
		result = self._improve_deposit_coverage()
		self._log_generic_build_result(result,  'deposit coverage storage')
		return self._translate_build_result(result)

class ClayDepositCoverageGoal(DepositCoverageGoal):
	def get_personality_name(self):
		return 'ClayDepositCoverageGoal'

	@property
	def deposit_class(self):
		return BUILDINGS.CLAY_DEPOSIT_CLASS

class MountainCoverageGoal(DepositCoverageGoal):
	def get_personality_name(self):
		return 'MountainCoverageGoal'

	@property
	def deposit_class(self):
		return BUILDINGS.MOUNTAIN_CLASS

decorators.bind_all(DepositCoverageGoal)
decorators.bind_all(ClayDepositCoverageGoal)
decorators.bind_all(MountainCoverageGoal)
