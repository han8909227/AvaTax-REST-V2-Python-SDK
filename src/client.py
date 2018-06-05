"""
AvaTax Software Development Kit for Python.

(c) 2004-2017 Avalara, Inc.

For the full copyright and license information, please view the LICENSE
file that was distributed with this source code.

@author     Robert Bronson
@author     Phil Werner
@author     Adrienne Karnoski
@author     Han Bao
@copyright  2004-2018 Avalara, Inc.
@license    https://www.apache.org/licenses/LICENSE-2.0
@link       https://github.com/avadev/AvaTax-REST-V2-Python-SDK
"""
from requests.auth import HTTPBasicAuth
from _str_version import str_type
from sys import platform
import client_methods
import datetime
import json
import glob
import os
import csv


class AvataxClient(client_methods.Mixin):
    """Class for our Avatax client."""

    def __init__(self, app_name=None, app_version=None, machine_name=None,
                 environment=None):
        """
        Initialize the sandbox client.

        By default the client object enviroment will be production. For
        sandbox API, set the enviroment variable to sandbox.

            :param  string  app_name: The name of your Application
            :param  string/integer  app_version:  Version of your Application
            :param  string  machine_name: Name of machine you are working on
            :param  string  enviroment: Default enviroment is production,
                input sandbox, for the sandbox API
        :return: object
        """

        if not all(isinstance(i, str_type) for i in [app_name,
                                                     machine_name,
                                                     environment]):
            raise ValueError('Input(s) must be string or none type object')
        self.base_url = 'https://rest.avatax.com'
        if environment:
            if environment.lower() == 'sandbox':
                self.base_url = 'https://sandbox-rest.avatax.com'
            elif environment[:8] == 'https://' or environment[:7] == 'http://':
                self.base_url = environment
        self.auth = None
        self.app_name = app_name
        self.app_version = app_version
        self.machine_name = machine_name
        self.client_id = '{}; {}; Python SDK; 18.5; {};'.format(app_name,
                                                                app_version,
                                                                machine_name)
        self.client_header = {'X-Avalara-Client': self.client_id}
        self._linux = True if platform == 'linux' or platform == 'linux2' or platform == 'darwin' else False
        self._content_cache = None   # use for offline tax calculation
        self._ziprates_cache = None  # use for offline tax calculation
        self._recTaskDir = None    # use for offline tax calculation
        self._default_comp = None  # use for offline tax calculation

    def add_credentials(self, username=None, password=None):
        """
        Configure this client for the specified username/password security.

        :param  string  username:    The username of your AvaTax user account
        :param  string  password:    The password of your AvaTax user account
        :param  int     accountId:   The account ID of your avatax account
        :param  string  licenseKey:  The license key of your avatax account
        :param  string  bearerToken: The OAuth 2.0 token provided by Avalara
        :return: AvaTaxClient

        Note: if you wish to use Bearer token, enter it as the ONLY argument to this method.
        """

        if not all(isinstance(i, str_type) for i in [username, password]):
            raise ValueError('Input(s) must be string or none type object')
        if username and not password:
            self.client_header['Authorization'] = 'Bearer ' + username
        else:
            self.auth = HTTPBasicAuth(username, password)
        return self


    def sync_offline_content(self, content_dir, zip_dir, loc_id, company_id=None, date=None):
        """
        Retrieve/refresh offline tax content for the specified company, location
        
        :param string content_dir The absolute path to the directory at which you wish to store/load Tax Content cache file
        :param string zip_dir:   The absolute path to the directory at which you wish to store/load Zip Rates cache file
        :param loc_id:   The ID number of the location to retrieve point-of-sale data.
        :optional param company_id     The ID number of the company that owns this location. Defaults to your default company
        :optional param string date:   The date for which point-of-sale data would be calculated, example will be '2018-05-20'. Defaults to today.
        """

        if not all(isinstance(i, str_type) for i in [content_dir, zip_dir]):
            raise ValueError('Directory path(s) must be a string')

        if date is None:
            date = datetime.datetime.today().strftime('%Y-%m-%d')
        elif not isinstance(date, str_type):
            raise ValueError('Date must be a string')

        default_comp = self._get_default_comp()
        content_response = self.build_tax_content_file_for_location(default_comp['id'], loc_id)
        content_json = json.loads(content_response.content)

        content_path = self._path_joiner(content_dir, 'retailTaxContent.json', loc_id)
        with open(content_path, 'w+') as file:
            json.dump(content_json, file)  # write and save json file


        zipct_list = []
        count = 0
        while len(zipct_list) < 100:  # to ensure the response 'your csv file is in build' is ignored
            zipct_response = self.download_tax_rates_by_zip_code(date)
            zipct_content = zipct_response.content.decode('utf-8')
            cr = csv.reader(zipct_content.splitlines(), delimiter=',')
            zipct_list = list(cr)
            count += 1
            if count > 10:  # prevent infinite loop if AvaTax is responding with error
                raise Exception('Failed to fetch zip rate data from AvaTax API')

        zipct_dict = self._zipct_helper(zipct_list)  # turn rates into dictionary
        zip_path = self._path_joiner(zip_dir, 'zipRates.json')
        with open(zip_path, 'w+') as file_two:
            json.dump(zipct_dict, file_two)  # save as json file

        return self


    def with_retail_tax_content(self, content_dir, loc_id):
        """
        Load tax content file in the path.
        
        :param string content_dir:   The absolute path to the directory at which you wish to store/load the Content cache file(s)
        :param int    loc_id:        The ID number of the location to retrieve point-of-sale cached content
        """

        if not isinstance(content_dir, str_type):
            raise ValueError('Path to file must be a string')
        if not isinstance(loc_id, int):
            raise ValueError('Location ID must be in integer')

        loc_file = content_dir + str(loc_id) + '_retailTaxContent.json'  # abs path to cached file for this loc

        if not os.path.isfile(loc_file): 
            raise IndexError('No content cache file found, call sync_offline_content method to cache files from AvaTax')

        with open(loc_file) as json_data:
            self._content_cache = json.load(json_data) # load tax content file to client

        return self


    def with_zipcode_tax_content(self, zip_dir):
        """
        Load zip code rates file in the path.

        :param string zip_dir:   The absolute path to the directory at which you wish to store/load Zip Rates cache file
        """
        if not isinstance(zip_dir, str_type):
            raise ValueError('Path to file must be a string')

        filter_string = zip_dir + '/*zipRates.json' # filter out non zipRate files
        recent_file = self._get_most_recent_file(filter_string)  # get the most recently cahced zip rate file

        if not os.path.isfile(recent_file):
            raise IndexError('No content cache file found, call sync_offline_content method to cache a files from AvaTax')

        with open(recent_file) as json_data:
            self._ziprates_cache = json.load(json_data) # load tax content file to client

        return self


    # def with_periodic_reconciliation_task(self, path):
    #     """
    #     Creates folder in the path directory to store/track failed transaction calls, in terms initiates a task to reconcilliation later

    #     :param string path:   The absolute path to the directory at which you wish to store/load failed calls
    #     """
    #     if not isinstance(path, str_type):
    #         raise ValueError('Path to file must be a string')

    #     taskDir = path + '/reconcilliationTasks'
    #     if not os.path.exists(taskDir):
    #         os.makedirs(taskDir)
    #     self._recTaskDir = taskDir

    #     return self
        

    def _path_joiner(self, path, file_name, loc_id=None):
        """Form full file path based on the directory path, filename and date."""

        today_date = datetime.datetime.today().strftime('%Y%m%d')
        file_name = str(loc_id) + '_' + file_name if loc_id else today_date + '_' + file_name

        if self._linux:  # considering file path structural difference in linux and windows
            output = os.path.join(path, file_name)
        else:
            output = path + r'\{}'.format(file_name)
        return output


    def _zipct_helper(self, zip_list):
        """Turn list of zipcode to dictionary for better lookup time."""

        zip_dict = {}
        for z in zip_list:
            code = z.pop(0)
            zip_dict[code] = z
        return zip_dict


    def _get_default_comp(self):
        """Retrieve the default company info for this client."""

        if self._default_comp:
            return self._default_comp
        response = self.query_companies()
        companies = response.json()['value']
        for c in companies:
            if c['isDefault']:
                self._default_comp = c
                break
        return self._default_comp


    def _get_most_recent_file(self, dir_filter):
        """Return the most recently edited/created file in the directory."""

        all_files = glob.glob(dir_filter)  # all files of the dir in list 
        files_by_date = []

        for f in all_files:
            stored_date = f.split('/')[-1].split('_')[-2]  # retrieve the date in file name
            files_by_date.append(int(stored_date))

        d = max(files_by_date)
        idx = files_by_date.index(d)
        output = all_files[idx]
        return output


# to generate a client object on initialization of this file, uncomment the script below
if __name__ == '__main__':  # pragma no cover
    """Creating a client with credential, must have env variables username & password."""
    client = AvataxClient('my test app',
                          'ver 0.0',
                          'my test machine',
                          'sandbox')
    c = client.add_credentials(os.environ.get('USERNAME', ''),
                               os.environ.get('PASSWORD', ''))
    print(client.ping().text)
    tax_document = {
        'addresses': {'SingleLocation': {'city': 'Irvine',
                                         'country': 'US',
                                         'line1': '123 Main Street',
                                         'postalCode': '92615',
                                         'region': 'CA'}},
        'commit': False,
        'companyCode': 'DEFAULT',
        'currencyCode': 'USD',
        'customerCode': 'ABC',
        'date': '2017-04-12',
        'description': 'Yarn',
        'lines': [{'amount': 100,
                  'description': 'Yarn',
                   'itemCode': 'Y0001',
                   'number': '1',
                   'quantity': 1,
                   'taxCode': 'PS081282'}],
        'purchaseOrderNo': '2017-04-12-001',
        'type': 'SalesInvoice'}

    request_model = {
        "companyCode": "DEFAULT",
        "responseType": "Json",
        "taxCodes": [
            "P0000000"
        ],
        "locationCodes": [
            "DEFAULT"
        ]}

    location_model =  {
        "id": 56789,
        "locationCode": "DEFAULT",
        "description": "Bob's Artisan Pottery",
        "addressTypeId": "Location",
        "addressCategoryId": "MainOffice",
        "line1": "2000 Main Street",
        "city": "Irvine",
        "county": "Orange",
        "region": "CA",
        "postalCode": "92614",
        "country": "US",
        "isDefault": True,
        "isRegistered": True,
        "dbaName": "Bob's Artisan Pottery",
        "outletName": "Main Office",
        "registeredDate": "2015-01-01T00:00:00",
        "settings": [
          {
            "questionId": 17,
            "value": "abcdefghij"
          }
        ]
    }
    zipPath = '/Users/han.bao/avalara/api_call/zipRates/'
    contentPath = '/Users/han.bao/avalara/api_call/myTax/'





