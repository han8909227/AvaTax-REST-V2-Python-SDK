from _str_version import str_type
import datetime
import json
import glob
import os
import csv

class Mixin:
    """Mixin for resiliency/offline tax calculation codes"""

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
            json.dump(zipct_dict, file_two)  # save dict as json file

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