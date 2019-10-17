"""
Tests for Course Teams configuration.
"""
from __future__ import absolute_import, unicode_literals

from collections import namedtuple

import ddt
import six
from django.test import TestCase

from ..teams_config import (
    ClusterTeamManagement,
    ClusterTeamVisibility,
    TeamsConfig,
    TeamsEnabledWithTeamsets,
    TeamsEnabledWithTopics,
    Teamset,
    Topic
)


@ddt.ddt
class TeamsConfigTests(TestCase):
    """
    Test cases for `TeamsConfig.from_dict` and `TeamsConfig.to_dict`.
    """

    @ddt.data(
        None,
        {},
        {"max_team_size": 5},
        {"teamsets": []},
        {"topics": None, "random_key": 88},
    )
    def test_empty_teams_config_is_disabled(self, data):
        teams_config = TeamsConfig.from_dict(data)
        assert not teams_config.is_enabled

    INPUT_DATA_1 = {
        "max_team_size": 5,
        "topics": [
            {
                "id": "bananas",
                "max_team_size": 10,
                "team_management": "student",
                "team_visibility": "private",
            },
            {
                "id": "bokonism",
                "name": "BOKONISM",
                "description": "Busy busy busy",
                "team_management": "instructor",
                # max_team_size should be ignored because of instructor management.
                "max_team_size": 2,
            },
            {
                # Clusters with duplicate IDs should be dropped.
                "id": "bananas",
                "name": "All about Bananas",
                "description": "Not to be confused with bandanas",
            },

        ],
    }

    OUTPUT_DATA_1 = {
        "max_team_size": 5,
        "topics": [
            {
                "id": "bananas",
                "name": "bananas",
                "description": "",
                "max_team_size": 10,
                "team_management": "student",
                "team_visibility": "private",
            },
            {
                "id": "bokonism",
                "name": "BOKONISM",
                "description": "Busy busy busy",
                "max_team_size": None,
                "team_management": "instructor",
                "team_visibility": "public",
            },
        ]
    }

    INPUT_DATA_2 = {
        "teamsets": [
            {
                # Cluster should be dropped due to lack of ID.
                "name": "Assignment about existence",
            },
            {
                # Cluster should be dropped due to invalid ID.
                "id": ["not", "a", "string"],
                "name": "Assignment about strings",
            },
            {
                # Cluster should be dropped due to invalid ID.
                "id": "Not a slug.",
                "name": "Assignment about slugs",
            },
            {
                # All fields invalid except ID;
                # Cluster will exist but have all fallbacks.
                "id": "horses",
                "name": {"assignment", "about", "horses"},
                "description": object(),
                "max_team_size": -1000,
                "team_management": "matrix",
                "team_visibility": "",
                "extra_key": "Should be ignored",
            },
        ],
    }

    OUTPUT_DATA_2 = {
        "max_team_size": None,
        "teamsets": [
            {
                "id": "horses",
                "name": "horses",
                "description": "",
                "max_team_size": None,
                "team_management": "student",
                "team_visibility": "public",
            },
        ],
    }

    @ddt.data(
        (INPUT_DATA_1, TeamsEnabledWithTopics, OUTPUT_DATA_1),
        (INPUT_DATA_2, TeamsEnabledWithTeamsets, OUTPUT_DATA_2),
    )
    @ddt.unpack
    def test_teams_config_round_trip(self, input_data, expected_class, expected_output_data):
        teams_config = TeamsConfig.from_dict(input_data)
        assert isinstance(teams_config, expected_class)
        actual_output_data = teams_config.to_dict()
        self.assertDictEqual(actual_output_data, expected_output_data)

    @ddt.data(
        (
            "not-a-dict",
            "must be a dict",
        ),
        (
            {"topics": [{'id': 'a-topic'}], "teamsets": [{'id': 'a-teamset'}]},
            "Only one of",
        ),
        (
            {"topics": "not-a-list"},
            "topics/teamsets must be list",
        ),
        (
            {"teamsets": {"also-not": "a-list"}},
            "topics/teamsets must be list",
        ),

    )
    @ddt.unpack
    def test_bad_data_gives_value_errors(self, data, error_message_snippet):
        with six.assertRaisesRegex(self, ValueError, error_message_snippet):
            TeamsConfig.from_dict(data)

    INVALID_VALUE = namedtuple('InvalidValue', ['message'])(
        message="this invalid value should be substituted for a fallback"
    )
    CONFIG_FROM_INVALID_VALUES = TeamsEnabledWithTeamsets(
        max_team_size=INVALID_VALUE,
        teamsets=[
            Teamset(
                "id-X",
                name=INVALID_VALUE,
                description=INVALID_VALUE,
                max_team_size=INVALID_VALUE,
                team_visibility=INVALID_VALUE,
                team_management=INVALID_VALUE,
            )
        ],
        source_data=INVALID_VALUE,
    )
    CONFIG_FROM_FALLBACK_VALUES = TeamsEnabledWithTeamsets(
        max_team_size=None,
        teamsets=[
            Teamset(
                "id-X",
                name="id-X",
                description="",
                max_team_size=None,
                team_management=ClusterTeamManagement.get_default(),
                team_visibility=ClusterTeamVisibility.get_default(),
            )
        ],
        source_data=None,
    )

    def test_fallbacks_and_equality(self):
        """
        Test that a config built with invalid arguments falls back to default
        values, and is equal to a config built with the default values.

        Also, test that source_data is ignored for equality.
        """
        assert self.CONFIG_FROM_INVALID_VALUES == self.CONFIG_FROM_FALLBACK_VALUES

    PRIVATE_TOPIC = Topic("id-X", team_management=ClusterTeamVisibility.private)
    PRIVATE_TOPIC_2 = Topic("id-X", team_management=ClusterTeamVisibility.private)
    PRIVATE_TEAMSET = Teamset("id-X", team_management=ClusterTeamVisibility.private)
    PUBLIC_TOPIC = Topic("id-X", team_management=ClusterTeamVisibility.public)

    def test_inequality(self):
        assert self.PRIVATE_TOPIC == self.PRIVATE_TOPIC_2
        assert self.PRIVATE_TOPIC != self.PRIVATE_TEAMSET
        assert self.PRIVATE_TOPIC != self.PUBLIC_TOPIC
