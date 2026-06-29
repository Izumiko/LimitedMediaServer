from flask import Blueprint, current_app, jsonify

from auth_utils import shall_authenticate_user
from common_utils import generate_success_response

# Create a Blueprint for plugin routes
plugin_blueprint = Blueprint('plugin', __name__)


# Default logging values for plugins


@plugin_blueprint.route('/list', methods=['POST'])
@shall_authenticate_user(plugin_blueprint)
def list_book_actions(user_details: dict) -> jsonify:
    """
    List all available actions for books.

    Args:
        user_details (dict): The details of the authenticated user.

    Returns:
        jsonify: A JSON response containing the list of available actions.
    """
    plugins = current_app.config['PLUGINS']['all']  # Retrieve all plugins from the app config

    results = []

    # Iterate through each plugin and check if it is ready and matches the user's feature flags
    for plugin in plugins:
        if plugin.is_ready() and (plugin.get_feature_flags() & user_details['features']) == plugin.get_feature_flags():

            j = plugin.to_json()

            for arg in j['args']:
                if arg['type'] == 'select':
                    temp_key = 'PLUGIN.DEFAULT.' + j['id'] + '_' + arg['id']

                    if temp_key in current_app.config and not current_app.config[temp_key] == '':
                        arg['default'] = current_app.config[temp_key]

            results.append(j)

    # Generate and return a success response with the list of plugins
    return generate_success_response('', {"plugins": results})
