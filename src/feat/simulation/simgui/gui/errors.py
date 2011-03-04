import gtk


class Error(object):

    def __init__(self, builder, driver):
        self.builder = builder

        self.model = self.builder.get_object('error_model')
        self.label = self.builder.get_object('error_tab')

        self.driver = driver
        self.driver.on_processed_callback(self._on_script_processed)

    def _on_script_processed(self):
        error = self.driver.get_error()
        if error:
            self.label.set_markup('<span color="red">%s</span>' % (
                self.label.get_text()))
            self.model.append([error])
        else:
            self.label.set_markup('<span>%s</span>' % (
                self.label.get_text()))
            self.model.clear()
