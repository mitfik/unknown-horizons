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

import random
import sys
from itertools import product

from horizons.command.building import Build, Tear
from horizons.command.unit import CreateUnit
from horizons.constants import BUILDINGS, UNITS
from horizons.util import Point
from horizons.world.pathfinding.pather import StaticPather

from tests.game import settle, game_test, RANDOM_SEED


def test_removal():
	rng = random.Random(RANDOM_SEED)
	for i in range(10):
		yield remove, rng.randint(0, 200), rng.randint(0, 200), rng.randint(0, 8)


@game_test
def remove(s, p, before_ticks, after_ticks, tear_index):
	"""
	Place a couple of buildings and tear down one randomly, run a while afterwards.
	Called by test_removal with different parameters.
	"""
	settlement, island = settle(s)
	settlement.branch_office.inventory.adjust_limit(sys.maxint)

	# Plant trees
	for (x, y) in product(range(23, 38), repeat=2):
		if s.random.randint(0, 1) == 1:
			tree = Build(BUILDINGS.TREE_CLASS, x, y, island, settlement=settlement)(p)
			assert tree
			tree.finish_production_now()

	jack = Build(BUILDINGS.LUMBERJACK_CLASS, 25, 30, island, settlement=settlement)(p)
	assert jack
	jack = Build(BUILDINGS.LUMBERJACK_CLASS, 35, 30, island, settlement=settlement)(p)
	assert jack

	# Throw some fish into the water
	for x in (25, 30, 35):
		school = Build(BUILDINGS.FISH_DEPOSIT_CLASS, x, 18, s.world, ownerless=True)(None)
		assert school
		school.finish_production_now()

	fisherman = Build(BUILDINGS.FISHERMAN_CLASS, 25, 20, island, settlement=settlement)(p)
	assert fisherman
	fisherman = Build(BUILDINGS.FISHERMAN_CLASS, 35, 20, island, settlement=settlement)(p)
	assert fisherman

	# Some wild animals in the forest
	for (x_off, y_off) in product([-5, -4, 4, 5], repeat=2):
		x = 30 + x_off
		y = 30 + y_off
		animal = CreateUnit(island.worldid, UNITS.WILD_ANIMAL_CLASS, x, y)(None)
		assert animal
		animal.finish_production_now()

	hunter = Build(BUILDINGS.HUNTER_CLASS, 30, 35, island, settlement=settlement)(p)
	assert hunter

	# Build a farm
	assert Build(BUILDINGS.FARM_CLASS, 26, 33, island, settlement=settlement)(p)
	assert Build(BUILDINGS.PASTURE_CLASS, 22, 33, island, settlement=settlement)(p)
	assert Build(BUILDINGS.PASTURE_CLASS, 26, 37, island, settlement=settlement)(p)

	# Build roads
	for (start, dest) in [(Point(27, 30), Point(30, 23)), (Point(32, 23), Point(35, 30)),
						  (Point(25, 21), Point(30, 23)), (Point(32, 23), Point(35, 21)),
						  (Point(30, 35), Point(32, 25)), (Point(26, 33), Point(27, 30))]:
		path = StaticPather.get_direct_path(island, start, dest)
		assert path
		for (x, y) in path:
			a = Build(BUILDINGS.TRAIL_CLASS, x, y, island, settlement=settlement)(p)

	s.run(seconds=before_ticks)
	# Tear down a random building that is not a trail or tree.
	target = [b for b in settlement.buildings if b.id not in (BUILDINGS.TRAIL_CLASS, BUILDINGS.TREE_CLASS)][tear_index]
	Tear(target)(p)
	s.run(seconds=after_ticks)

