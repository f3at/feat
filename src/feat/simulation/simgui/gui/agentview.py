import gtk

from feat.agents.base import agent

COLUMNS = agent.registry


def setup_menu(menu, menu_items):
    items = []
    for key in COLUMNS.keys():
        items.append(key)
    items.sort()
    for item in items:
        col = COLUMNS[item]
        menu_item = gtk.CheckMenuItem(item.replace('_', ' '))
        menu_item.set_active(True)
        gtk.Menu.append(menu, menu_item)
        if item not in menu_items:
            menu_items[item] = menu_item
