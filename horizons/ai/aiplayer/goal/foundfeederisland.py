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
from horizons.util.python import decorators

class FoundFeederIslandGoal(SettlementGoal):
	@property
	def priority(self):
		return 650

	@property
	def active(self):
		return self.settlement_manager.tents >= 16 and self.owner.need_feeder_island(self.settlement_manager) and \
			not self.owner.have_feeder_island() and self.owner.can_found_feeder_island()

	def execute(self):
		self.settlement_manager.log.info('%s waiting for a feeder islands to be founded', self)
		self.owner.found_feeder_island()

decorators.bind_all(FoundFeederIslandGoal)