class Resource(object):
    '''
        This class handles all the operations related to resources
    '''
    def __init__(self, name, value):
        self._name = name
        self._value = value

    def get_name(self):
        return self._name

    def get_value(self):
        return self._value


class ResourceContainter(object):
    '''
        This class provides us operations to control a set of resources
    '''
    def __init__(self):
        self._bid_id = bid_id
        self._resources = {}

    def append_resource(r, force=False):
        ''' Append a resource to the container '''
        # be sure the resource we're adding is
        if (r.get_name() in self._resources.keys() and force)
            or r.get_name() not in self._resources.keys():
            self._resources[r.get_name()] = r
        else:
            raise ResourceAlreadyExists # !!!!!!!!!!!!!!!!!!!!!!!!!!!!

    def append_resources(rlist, force=False):
        ''' Append a list of resources to the container '''
        for r in rlist:
            self.append_resource(r, force)

    def del_resource(r):
        ''' Remove a resource from a container '''
        try:
            del(self._resources[r.get_name()])
        except:
            raise ResourceNotFound # !!!!!!!!!!!!!!

    def get_resources_names():
        return self._resources.keys()


class ResourceDescriptor(object):
    def __init__(self):
        self._resources = ResourceContainer()
        self._preallocated = {)
        self._allocated = {}


    def append_resource(r):
        self._resources.append_resource(r)


    def append_resources(rlist):
        self._resources.append_resources(rlist)


    def available(bid_id):
        # this part of code should be sincronized? might happend that it tells
        # to two *threads* that there're free resources when they're actually
        # overlapping?
        preallocated = []

        try:
            preallocated = self._preallocated[bid_id]
        except Exception:
            pass # !!!!!!!!!!!!!!!!!!!!!! such bid does not exist!!!!!!!!!!!!!!

        # check that we're not asking for a resource that we don't provide
        n_resources = set(self._resources.get_resources_names())
        n_preallocated = set(preallocated.get_resources_names())
        #diff = []
        #[diff.append(x) for x in n_preallocated if x not in n_resources]
        diff = (n_preallocated - n_resources)

        if len(diff) > 0:
            print "FAIL" # !!!!

        self._resources - self._preallocated - self._allocated



    def preallocate_resources(rlist, bid_id, on_expire=None, ttl=10):
        '''
        Preallocates all the resources at rlist, allowing them to be allocated
        for TTL time and if expired will call method on_expire
        '''
        # in case it's possible
        if (bid_id not in self._preallocated):
            self._preallocated[bid_id] = ResourceContainer()
            for r in rlist:
                self._preallocated[bid_id].append(r)
        else:
            raise BidAlreadyPreallocated


    def allocate(bid_id):
        '''
        Allocates all the resources belonging to the provided bid id, so it not
        interferes with other bids
        '''
        pass

