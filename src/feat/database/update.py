from feat.database.interface import ResignFromModifying


def attributes(document, params, force_save=False):
    changed = False
    if isinstance(params, dict):
        params = params.iteritems()
    for key, value in params:
        if not isinstance(key, tuple):
            key = (key, )
        actual = document
        for part in key[:-1]:
            if isinstance(actual, dict) or isinstance(part, int):
                actual = actual[part]
            else:
                actual = getattr(actual, part)

        if isinstance(actual, dict):
            if actual.get(key[-1]) != value:
                actual[key[-1]] = value
                changed = True
        elif getattr(actual, key[-1]) != value:
            setattr(actual, key[-1], value)
            changed = True

    if force_save or changed:
        return document
    else:
        raise ResignFromModifying()


def append_to_list(document, key, value, unique=False):
    changed = False
    llist = getattr(document, key)
    if not isinstance(llist, list):
        setattr(document, [value])
        changed = True
    elif not (unique and value in llist):
        llist.append(value)
        changed = True
    if changed:
        return document
    else:
        raise ResignFromModifying()


def extend_list(document, key, values):
    llist = getattr(document, key)
    if not isinstance(llist, list):
        setattr(document, key, values)
    else:
        llist.extend(values)
    return document


def add_to_set(document, key, value):
    sset = getattr(document, key)
    if not isinstance(sset, set):
        setattr(document, key, set([value]))
    else:
        if value in sset:
            raise ResignFromModifying()
        else:
            sset.add(value)
    return document


def remove_from_set(document, key, value):
    sset = getattr(document, key)
    if not isinstance(sset, set):
        raise ResignFromModifying()
    else:
        if value not in sset:
            raise ResignFromModifying()
        else:
            sset.remove(value)
    return document


def step(method, *args, **kwargs):
    return (method, args, kwargs)


def steps(document, *updates):
    changed = False
    for method, args, kwargs in updates:
        try:
            document = method(document, *args, **kwargs)
            if document is None:
                return
            changed = True
        except ResignFromModifying:
            pass
    if changed:
        return document
    else:
        raise ResignFromModifying()


def delete(document):
    return None


def create_link(document, *args, **kwargs):
    document.links.create(*args, **kwargs)
    return document
