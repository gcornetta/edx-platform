"""
Configuration for Course Teams feature.

Used by `common/lib/xmodule/xmodule/course_module.py` and
`lms/djangoapps/teams`.
"""
from __future__ import absolute_import, unicode_literals

import logging
import re
from abc import ABCMeta, abstractmethod, abstractproperty
from enum import Enum

import six

log = logging.getLogger(__name__)


@six.add_metaclass(ABCMeta)  # Allows TeamsConfig to have abstract methods
class TeamsConfig(object):
    """
    Abstract base teams configuration for a course.
    """
    def __init__(self, source_data=None):
        self.source_data = source_data

    @abstractproperty
    def is_enabled(self):
        pass

    @classmethod
    def from_dict(cls, data):
        """
        Given a dictionary, construct a TeamsConfig instance.

        If data missing or empty, falls back to sane values.
        Raises ValueError on invalid types.
        """
        if data is None:
            return TeamsDisabled(source_data=None)
        if not isinstance(data, dict):
            raise ValueError("data to build TeamConfig must be a dict")
        max_team_size = _clean_max_team_size(data.get("max_team_size"))
        topics_data = data.get(ClusteringScheme.topics.value)
        teamsets_data = data.get(ClusteringScheme.teamsets.value)
        if topics_data and teamsets_data:
            raise ValueError("Only one of (teams, topics) may be specified.")
        elif topics_data:
            topics = cls._load_clusters(Topic, topics_data)
            if topics:
                return TeamsEnabledWithTopics(
                    topics=topics,
                    max_team_size=max_team_size,
                    source_data=data,
                )
        elif teamsets_data:
            teamsets = cls._load_clusters(Teamset, teamsets_data)
            if teamsets:
                return TeamsEnabledWithTeamsets(
                    teamsets=teamsets,
                    max_team_size=max_team_size,
                    source_data=data,
                )
        return TeamsDisabled(source_data=data)

    @staticmethod
    def _load_clusters(clusters_class, clusters_data):
        """
        Load list of Clusters from list of dictionaries.
        """
        if not isinstance(clusters_data, list):
            raise ValueError("topics/teamsets must be list; is {}".format(
                type(clusters_data)
            ))
        clusters = []
        cluster_ids = set()
        for cluster_data in clusters_data:
            try:
                cluster = clusters_class.from_dict(cluster_data)
            except ValueError:
                # Drop badly-configured clusters.
                log.exception("Error while parsing team cluster; skipping cluster.")
                continue
            if cluster.id in cluster_ids:
                log.error(
                    "Duplicated cluster ID: {} " + cluster.id +
                    ". Ignoring all clusters except first with ID."
                )
                continue
            clusters.append(cluster)
            cluster_ids.add(cluster.id)
        return clusters

    @abstractmethod
    def to_dict(self):
        """
        Return this teams config as JSON-ifyable dictionary.
        """
        pass

    @abstractmethod
    def __eq__(self, other):
        pass

    def __ne__(self, other):
        """
        Overrides default inequality to be the inverse of our custom equality.

        Safe to remove once we're in Python 3 -- Py3 does this for us.
        """
        return not self.__eq__(other)


class TeamsDisabled(TeamsConfig):
    """
    Teams are disabled for a course.
    """
    @property
    def is_enabled(self):
        return False

    def to_dict(self):
        """
        Return this teams config as JSON-ifyable dictionary.
        """
        return {}

    def __eq__(self, other):
        """
        Checks equality, based on __class__
        (source_data is ignored for this check).
        """
        return isinstance(other, self.__class__)


class TeamsEnabled(TeamsConfig):
    """
    Abstract class indicating teams are enabled for a course.

    The configuration doesn't define the teams themselves,
    but defines the team clusters and the constraints on the teams within
    those clusters.

    Note that a "cluster" is a generic term for sets of teams,
    currently including Topics and Teamsets. The concrete subclasses of this
    class specify topics or teamsets.
    """
    def __init__(self, max_team_size=None, source_data=None):
        self.max_team_size = max_team_size
        super(TeamsEnabled, self).__init__(source_data)

    @property
    def is_enabled(self):
        return True

    @abstractproperty
    def clustering_scheme(self):
        pass

    @abstractproperty
    def clusters(self):
        pass

    @property
    def clusters_by_id(self):
        return {cluster.id: cluster for cluster in self.clusters}

    def get_max_team_size_for_cluster(self, cluster_id):
        """
        Get the maximum team size for a cluster, or None if no maximum.
        """
        try:
            cluster = self.clusters[cluster_id]
        except KeyError:
            raise ValueError("Cluster '{}' does not exist.".format(cluster_id))
        if not cluster.team_management.team_size_limit_enabled:
            return None
        if cluster.max_team_size is not None:
            # Explicitly check against None,
            # because we do not want to treat Zero as None.
            return cluster.max_team_size
        return self.max_team_size

    def to_dict(self):
        """
        Return this teams config as JSON-ifyable dictionary.
        """
        clusters_key = self.clustering_scheme.value
        clusters = [cluster.to_dict() for cluster in self.clusters]
        return {
            clusters_key: clusters,
            "max_team_size": self.max_team_size,
        }

    def __eq__(self, other):
        """
        Checks equality, based on __class__, clusters, and max_team_size
        (source_data is ignored for this check).
        """
        return (
            isinstance(other, self.__class__) and
            self.clusters == other.clusters and
            self.max_team_size == other.max_team_size
        )


class TeamsEnabledWithTopics(TeamsEnabled):
    """
    Teams are enabled for a course, and configured to use topics as clusters.
    """
    def __init__(self, topics, max_team_size=None, source_data=None):
        self.topics = topics
        super(TeamsEnabledWithTopics, self).__init__(
            max_team_size=max_team_size,
            source_data=None,
        )

    @property
    def clustering_scheme(self):
        return ClusteringScheme.topics

    @property
    def clusters(self):
        return self.topics


class TeamsEnabledWithTeamsets(TeamsEnabled):
    """
    Teams are enabled for a course, and configured to use teamsets as clusters.
    """
    def __init__(self, teamsets, max_team_size=None, source_data=None):
        self.teamsets = teamsets
        super(TeamsEnabledWithTeamsets, self).__init__(
            max_team_size=max_team_size,
            source_data=None,
        )

    # Temporarily disable this configuration until it is implemented (MST-9).
    def is_enabled(self):
        return False

    @property
    def clustering_scheme(self):
        return ClusteringScheme.teamsets

    @property
    def clusters(self):
        return self.teamsets


@six.add_metaclass(ABCMeta)  # Allows Cluster to have abstract methods
class Cluster(object):
    """
    A configuration for a set of teams.
    May be either a Topic or a Teamset.

    Configuration options:
    * id - URL slug uniquely identifying this cluster within the course.
    * name - Human-friendly name of the cluster.
    * description - Human-friendly description of the cluster.
    * max_team_size - Maximum size allowed for teams within cluster.
        If None, falls back to TeamsConfig-level max_team_size.
        If that is None, then there is no team size maximum.
    * team_management - Instructor/Student team management.
    * team_visibility - Public/Private team visibility.
    """
    def __init__(
            self,
            id_,
            name=None,
            description=None,
            max_team_size=None,
            team_management=None,
            team_visibility=None
    ):
        self._validate_id(id_)
        self.id = id_
        self._name = name
        self._description = description
        self._max_team_size = max_team_size
        self._team_management = team_management
        self._team_visibility = team_visibility

    @abstractmethod
    def get_clustering_scheme(cls):  # pylint: disable=no-self-argument
        """
        Returns the clustering scheme that uses this type of cluster.
        """
        # Override as a classmethod.
        pass

    @property
    def name(self):
        if self._name and isinstance(self._name, six.string_types):
            return self._name
        else:
            return self.id

    @property
    def description(self):
        if isinstance(self._description, six.string_types):
            return self._description
        else:
            return ""

    @property
    def max_team_size(self):
        if self.team_management.team_size_limit_enabled:
            return _clean_max_team_size(self._max_team_size)
        else:
            return None

    @property
    def team_management(self):
        return _clean_enum_value(self._team_management, ClusterTeamManagement)

    @property
    def team_visibility(self):
        return _clean_enum_value(self._team_visibility, ClusterTeamVisibility)

    _valid_id_pattern = r'[A-Za-z0-9_-]+'
    _valid_id_regexp = re.compile('^{}$'.format(_valid_id_pattern))

    @classmethod
    def _validate_id(cls, id_):
        """
        Raise ValueError if `id_` is not valid URL slug.
        """
        is_string = isinstance(id_, six.string_types)
        if is_string and cls._valid_id_regexp.match(id_):
            return
        raise ValueError(
            "cluster id must be string matching {}; is {}".format(
                cls._valid_id_pattern, id_
            )
        )

    @classmethod
    def from_dict(cls, data):
        """
        Parse a Cluster from a dictionary.
        """
        if not isinstance(data, dict):
            raise ValueError(
                "data must be dictionary; is {}".format(type(data))
            )
        return cls(
            data.get('id'),
            name=data.get('name'),
            description=data.get('description'),
            max_team_size=data.get('max_team_size'),
            team_management=data.get('team_management'),
            team_visibility=data.get('team_visibility'),
        )

    def to_dict(self):
        """
        Return this Cluster as JSON-ifyable dictionary.
        """
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'max_team_size': self.max_team_size,
            'team_management': self.team_management.value,
            'team_visibility': self.team_visibility.value,
        }

    @property
    def are_team_discussions_private(self):
        return self.team_visibility == ClusterTeamVisibility.private

    def __eq__(self, other):
        """
        Checks equality, based on __class__ and values of properties
        (*not* the values of the arguments to the constructor).
        """
        return (
            isinstance(other, self.__class__) and
            self.id == other.id and
            self.name == other.name and
            self.description == other.description and
            self.max_team_size == other.max_team_size and
            self.team_management == other.team_management and
            self.team_visibility == other.team_visibility
        )

    def __ne__(self, other):
        """
        Overrides default inequality to be the inverse of our custom equality.

        Safe to remove once we're in Python 3 -- Py3 does this for us.
        """
        return not self.__eq__(other)


class Topic(Cluster):
    """
    A configuration for a set of teams, which are
    generally formed for the purpose of discussing some subject.

    This is the type of `Cluster` that is used under `ClusteringScheme.topics`.
    """
    @classmethod
    def get_clustering_scheme(cls):
        """
        Returns the clustering scheme that uses this type of cluster.
        """
        return ClusteringScheme.topics


class Teamset(Cluster):
    """
    A configuration for a set of teams, which are
    generally formed for the purpose of completing a set of assignments.

    This is the type of `Cluster` that is used under `ClusteringScheme.teamsets`.
    """
    @classmethod
    def get_clustering_scheme(cls):
        """
        Returns the clustering scheme that uses this type of cluster.
        """
        return ClusteringScheme.teamsets


class ClusteringScheme(Enum):
    """
    The scheme with which the course's teams are divided into clusters.

    Under a "topics" scheme, each cluster is a Topic, which generally is a set
    teams formed for the purpose of discussing some subject.
    Students may join ONE TEAM per COURSE.

    Under a "teamsets" scheme, each cluster is a Teamset, which generally is a
    set of teams formed for the purpose of completing a set of assignments.
    Students may join ONE TEAM per TEAMSET.
    This scheme allows greater flexibility in that a student may work with
    different teams of students for different assignments, all within the
    same course.
    """
    topics = "topics"
    teamsets = "teamsets"

    @classmethod
    def get_default(cls):
        return cls.topics


class ClusterTeamManagement(Enum):
    """
    Management scheme for teams within a cluster.

    Under "instructor" management, only instructors may create and assign teams,
    and they may do so using bulk CSV upload (MST-9) or from a UI within the
    team (MST-13).
    Students may not modify create teams, join them, leave them, or otherwise
    modify team membership within the cluster.

    Under "student" management, students may freely create, join, and leave
    teams (within the constraints of the ClusteringScheme).
    Instructors may also modify team membership from the UI within the team,
    but nothing stops the students from overriding the instructor's changes.
    """
    instructor = "instructor"
    student = "student"

    @classmethod
    def get_default(cls):
        return cls.student

    @property
    def team_size_limit_enabled(self):
        return self == self.student


class ClusterTeamVisibility(Enum):
    """
    Visibility setting for teams within a cluster.

    Under "public" visibility, any enrolled student can see team details,
    discussions, etc.

    Under "private" visibility, only team members and course staff can team
    details, discussions, etc.

    This may be reevaluated in MST-23.
    """
    public = "public"
    private = "private"

    @classmethod
    def get_default(cls):
        return cls.public


def _clean_enum_value(value, enum_class):
    """
    Return `value` as an `enum_class` instance OR a sane default.

    If `value` is instance of `enum_class`, return it.
    Else, try to parse `value` into `enum_class` instance.
    Otherwise, try to return the default `enum_class` value.
    Finally, just return None.
    """
    if isinstance(value, enum_class):
        return value
    try:
        return enum_class(value)
    except ValueError:
        pass
    try:
        return enum_class.get_default()
    except AttributeError:
        return None


def _clean_max_team_size(value):
    """
    Return `value` if it's a positive int, otherwise None.
    """
    if not isinstance(value, six.integer_types):
        return None
    if value < 0:
        return None
    return value
