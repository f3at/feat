Merging notes
-------------

    - Changes in exception and failure handling.
        - Exceptions and Failure are now serialized.
        - mutable method now ALWAYS return a Deffered when called from outside of the Ball. If the method raises an exception it's equivalent to returning fiber.fail(e).
        - mutable method called from another mutable method can raise exceptions, only when the exception pass the limit of the ball it is converted to Deferred.
        - Exception should not be serializable explicitly, not inheriting from Serializable and be registered if they do not implements __eq__ and __ne__.
