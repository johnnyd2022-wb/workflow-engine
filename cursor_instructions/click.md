I want to add python click into my application so I can  have easy entry points into my app for containers as it will be a mono repo with multiple services spun up

Everything for the application is to live inside the app dirctory.
I have started a new directory called cli for the click code to live.

I need the following tasks done in this order;
 - install python click as a dependency if it isn't already in uv pyproject.toml
 - add core click code to create and register click groups
 - create click group for the main app.py function to start the entire app
 - update dockerfile.multi test stage to use new click command to run the application
 - anything else that is required for click that I have missed

If you are unsure about anything just ask.