from zope.interface import Interface, Attribute

class Node(Interface):
    ''' This class is used to create instances of a Profile node. Used as a
    basic unit of it. '''

    _id = Attribute("Random UUID(v4) for that node.")
    _component = Attribute("Flumotion component relative to that node")
    _feeders = Attribute("List of feeders for that node. Empty
            list if it's the parent")
    _being_used = Attribute("Boolean used for cost calculations
            that if set to True indicates that should be counted for overall costs")


    def __call__(feeders=[], being_used=True):
        '''
            Create a Node and initialize its values:
            @param feeders: Node instances that feed the current one
            @type feeders: list
            @param being_used: Indicates if the current node is in use
            @type being_used: boolean
        '''

    def set_id(new_id):
        '''
            Sets a new identifier to the given node.
            @param new_id: new uuid4
            @type new_id: uuid4 as a hex string (uuid.uuid4().hex)
        '''

class Profile(Interface):
    ''' Handles the data within a flow. Built up from Node objects '''

    _id = Attribute("Random UUID(v4) for that Profile.")
    _entry_node = Attribute("Entry point for the Profile node
            reference, whose parent is None(not feeded by others")
    _parent = Attribute("")
    _nodes = Attribute("Dictionary containing the nodes within a
            profile.")
    _profile = Attribute("python-graph digraph built up from
            nodes identifiers")


    def __call__(nodes={}):
        '''
            Initializes and prepares Profile.
            @param nodes: Nodes to be added to the Profile
            @type nodes:  Dictonary of the form {'nodeid': <node instance>}
        '''


    def add_node(node):
        '''
            Given a node connects it to the graph and redraws it. Will raise an
            exception if the feeders of such node aren't in the profile.
            @param node: node to be added
            @type node: instance of Node class
        '''


    def remove_node(node_id):
        '''
            Remove the node identified with node_id and rebuild the graph.
            @param node_id: uuid4 within the profile to be removed
            @type node_id: uuid4 as a hex string (uuid.uuid4().hex)
        '''


    def set_entry_node(node_id):
        '''
            Changes the entry node within a Profile to the one identified by
            node_id. If the node_id is not found at Profile it will raise a
            KeyError exception.
            @param node_id: uuid4 within the profile to be set as entry point
            @type node_id: uuid4 as a hex string (uuid.uuid4().hex)
        '''


    def get_entry_node():
        ''' Returns the instance of the entry node '''


    def set_parent(obj):
        ''' Indicates the Profile parent. Useful for GroupProfiles'''


    def calculate_cost():
        ''' Provides the cost of a given Profile '''


class GroupProfile(Interface):
    '''
        Handles a group of Profiles and associated data like cost. Can perform
        group optimizations, and cost calculations.
    '''

    _profiles = Attribute("Dictionary containing the profiles within a group")
    _entry_node = Attribute("dummy neutral object from where all Profiles hang")
    _graph = Attribute("python-graph digraph built up from Profiles inside the
            group")


    def __call__():
       ''' Initializes and prepares GroupProfile. '''


    def add_profile(profile):
        '''
            Add a profile to the group and rebuild the graph. If the profile is
            already in it will raise a IdAlreadyInUse exception.
            @param profile: profile to be added
            @type profile: instance of Profile class
        '''

    def add_profiles(profiles=[]):
        '''
            Given a list of profiles add them calling add_profile() method
            @param profiles: array of profiles
            @type profiles: list of profile instances
        '''


    def remove_profile(profile_id):
        '''
            Remove a profile from the Group and rebuild the graph
            @param profile_id: uuid4 of the profile to be removed
            @type profile_id: uuid4 as a hex string (uuid.uuid4().hex)
        '''


    def remove_profiles(profiles=[]):
        '''
            Given a list of profiles remove them calling remove_profile() method
            @param profile_id: uuid4 of the profile to be removed
            @type profile_id: uuid4 as a hex string (uuid.uuid4().hex)
        '''

    def change_profile(profile_id, profile):
        '''
            Given a profile identifier and a profile object if the profile is
            already in the Group it will be changed with the given one.
            @param profile_id: uuid4 of the profile to be changed
            @type profile_id: uuid4 as a hex string (uuid.uuid4().hex)
            @param profile: profile to be added
            @type profile: instance of Profile class
        '''
