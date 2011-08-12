Merging notes
-------------

* Recipient's shard property is deprecated, please use the route property.
* To copy a message use duplicate() method not clone().
* Emulation agency's initate() method signature changed.
  Because it can accept multiple messaging backend, the messaging
  parameter has been moved to the end.
  Use initiate(db, journal, mesg) instead of initate(mesg, db, journal).