import numpy as np
import json
from scipy.optimize import minimize_scalar
from read_mars import read_mars
from fact.analysis.statistics import li_ma_significance

from calc_a_eff_parallel import calc_a_eff_parallel_hd5
from read_data import histos_from_list_of_mars_files, calc_onoffhisto
from on_time_parallel import calc_on_time
from plotting import plot_spectrum, plot_theta

from tqdm import tqdm

def symmetric_log10_errors(value, error):
    """ Calculate upper and lower error, that appear symmetric in loglog-plots.

    :param value: ndarray or float
    :param error: ndarray or float
    :return: array of lower error and upper error.
    """
    error /= (value * np.log(10))
    error_l = value - np.ma.power(10, (np.ma.log10(value) - error))
    error_h = np.ma.power(10, (np.ma.log10(value) + error)) - value
    return [error_l, error_h]

class Spectrum:
    """ Class containing FACT spectra and additional information"""
    list_of_variables = ["use_correction_factors",
                         "theta_square",
                         "alpha",
                         "list_of_ceres_files",
                         "ganymed_file_mc",
                         "run_list_star",
                         "energy_binning",
                         "zenith_binning",
                         "energy_labels",
                         "zenith_labels",
                         "ganymed_file_data",
                         "energy_center",
                         "energy_error",
                         "on_time_per_zd",              # 1D-Array of On-Time per ZenithDistance bin
                         "total_on_time",               # Total On-Time of the observation
                         "on_histo_zenith",             # 2D-Histogram Energy:ZenithDistance of On-Events
                         "off_histo_zenith",            # 2D-Histogram Energy:ZenithDistance of Off-Events
                         "on_histo",                    # 1D-Histogram in Energy of On-Events
                         "off_histo",                   # 1D-Histogram in Energy of Off-Events
                         "significance_histo",          # 1D-Histogram in Energy of Significance
                         "excess_histo",                # 1D-Histogram in Energy of Excess_Events
                         "excess_histo_err",            # 1D-Histogram in Energy of Error of Excess_Events
                         "n_on_events",                 # Total number (sum) of On-Events
                         "n_off_events",                # Total number (sum) of Off-Events
                         "n_excess_events",             # Total number (sum) of Excess-Events
                         "n_excess_events_err",         # Estimated error of total number of Excess_events
                         "overall_significance",        # Overall Significance (computed with total On- and Off-events)
                         "theta_square_binning",        # 1D-Histogram of binning in theta_square
                         "on_theta_square_histo",       # 1D-Histogram in Theta Square of On-Events
                         "off_theta_square_histo",      # 1D-Histogram in Theta Square of Off-Events
                         "effective_area",              # 2D-Histogram Energy:ZenithDistance of Effective Area
                         "scaled_effective_area",       # effective_area scaled by On-Time per zenith bin
                         "differential_spectrum",       # 1D-Histogram, in energy of spectral points dN/dE
                         "differential_spectrum_err",    # 1D-Histogram, estimated error of spectral points
                         # Dict containing overall stats: number of on, off and excess events, 
                         # total on-time in hours, significance:
                         "stats"]

    def __init__(self,
                 run_list_star=None,
                 theta_sq=0.085,
                 correction_factors=False,
                 ebins=None,
                 elabels=None,
                 zdbins=None,
                 zdlabels=None,
                 ganymed_file_data=None,
                 ganymed_file_mc=None,
                 list_of_ceres_files=None,
                 alpha=0.2
                 ):

        self.use_correction_factors = correction_factors
        self.theta_square = theta_sq
        self.alpha = alpha

        self.list_of_ceres_files = list_of_ceres_files
        self.ganymed_file_mc = ganymed_file_mc

        if run_list_star:
            self.run_list_star = run_list_star

        if ebins:
            self.energy_binning = ebins
        else:
                self.energy_binning = np.logspace(np.log10(200.0), np.log10(50000.0), 9)
        if zdbins:
            self.zenith_binning = zdbins
        else:
            self.zenith_binning = np.linspace(0, 60, 15)

        if elabels:
            self.energy_labels = np.array(elabels)
        else:
            self.energy_labels = np.arange(len(self.energy_binning) - 1)

        if zdlabels:
            self.zenith_labels = np.array(zdlabels)
        else:
            self.zenith_labels = np.arange(len(self.zenith_binning) - 1)
        if ganymed_file_data:
            self.ganymed_file_data = ganymed_file_data

        self.energy_center = None
        self.energy_error = None

        # Declare Placeholder variables
        self.on_time_per_zd = None
        self.total_on_time = None

        self.on_histo_zenith = None
        self.off_histo_zenith = None
        self.on_histo = None
        self.off_histo = None
        self.significance_histo = None
        self.excess_histo = None
        self.excess_histo_err = None
        self.n_on_events = None
        self.n_off_events = None
        self.n_excess_events = None
        self.n_excess_events_err = None
        self.overall_significance = None

        self.theta_square_binning = None
        self.on_theta_square_histo = None
        self.off_theta_square_histo = None

        self.effective_area = None
        self.scaled_effective_area = None

        self.differential_spectrum = None
        self.differential_spectrum_err = None

        self.stats = {}

    ##############################################################
    # Define functions to set variables
    ##############################################################

    def set_energy_binning(self, ebins, elabels=None):
        self.energy_binning = ebins
        if elabels:
            self.energy_labels = elabels
        else:
            self.energy_labels = range(len(ebins)-1)

    def set_zenith_binning(self, zdbins, zdlabels=None):
        self.zenith_binning = zdbins
        if zdlabels:
            self.zenith_labels = zdlabels
        else:
            self.zenith_labels = range(len(zdbins) - 1)

    def set_theta_square(self, theta_square):
        self.theta_square = theta_square

    def set_correction_factors(self, true_or_false=True):
        self.use_correction_factors = true_or_false

    def set_alpha(self, alpha):
        self.alpha = alpha

    ##############################################################
    # Define functions to set used data and mc
    ##############################################################

    def set_list_of_ceres_files(self, path):
        self.list_of_ceres_files = path

    def set_ganymed_file_mc(self, path):
        self.ganymed_file_mc = path

    def set_ganymed_file_data(self, path):
        self.ganymed_file_data = path

    def set_run_list_star(self, star_list):
        self.run_list_star = star_list

    ##############################################################
    # Optimise Theta and optimise e-binning
    ##############################################################
    def read_events(self):
        select_leaves = ['DataType.fVal', 'MPointingPos.fZd', 'FileId.fVal',
                         'MTime.fMjd', 'MTime.fTime.fMilliSec', 'MTime.fNanoSec',
                         'MHillas.fSize', 'ThetaSquared.fVal', 'MNewImagePar.fLeakage2',
                         'MHillas.fLength', 'MHillas.fWidth']
        data = read_mars(self.ganymed_file_data, leaf_names=select_leaves)
        data = data.assign(energy=lambda x: (
                                             np.power(29.65 * x["MHillas.fSize"],
                                                      (0.77 / np.cos((x["MPointingPos.fZd"] * 1.35 * np.pi)
                                                       / 360))) + x["MNewImagePar.fLeakage2"] * 13000))
        return data

    def optimize_theta(self):
        events = self.read_events()

        def overall_sigma(x, data=None):
            source_data = data.loc[data["ThetaSquared.fVal"] < x]
            on_data = len(source_data.loc[source_data["DataType.fVal"] == 1.0])
            off_data = len(source_data.loc[source_data["DataType.fVal"] == 0.0])
            return 100 - li_ma_significance(on_data, off_data)

        result = minimize_scalar(overall_sigma, bounds=[0.01, 0.1], method='Bounded', args=events)
        self.theta_square = result.x
        return result

    def optimize_ebinning(self):
        data = self.read_events()

        source_data = data.loc[data["ThetaSquared.fVal"] < self.theta_square]
        on_data = source_data.loc[source_data["DataType.fVal"] == 1.0]
        off_data = source_data.loc[source_data["DataType.fVal"] == 0.0]

        on_data = on_data.copy()
        off_data = off_data.copy()

        on_data.sort_values("energy", ascending=False, inplace=True)
        off_data.sort_values("energy", ascending=False, inplace=True)

        sigma_per_bin = 3
        bin_edges = [0]
        bin_edges_energy = [50000]
        sigma_list = []
        length = len(on_data)
        for i in tqdm(range(length)):
            low_index = bin_edges[-1]
            high_index = i
            n_on = len(on_data.iloc[low_index:high_index])
            n_off = len(off_data.loc[(off_data.energy >= on_data.iloc[high_index - 1].energy) & (
                        off_data.energy <= on_data.iloc[low_index].energy)])
            sigma_li_ma = li_ma_significance(n_on, n_off)
            e_high = on_data.iloc[high_index - 1].energy
            e_low = on_data.iloc[low_index].energy
            size = np.abs((e_high - e_low) / e_low)
            if ((sigma_li_ma >= sigma_per_bin) & (size > 0.5)) | (i == length - 1):
                bin_edges.append(high_index)
                bin_edges_energy.append(int(on_data.iloc[high_index - 1].energy) + 1)
                sigma_list.append(sigma_li_ma)
        print(bin_edges_energy)
        self.energy_binning = np.array(np.sort(bin_edges_energy), dtype=np.float)

        self.energy_labels = np.arange(len(self.energy_binning) - 1)

    ##############################################################
    # Define functions to read data and calculate spectra
    ##############################################################

    def calc_ontime(self, data=None, n_chunks=8, use_multiprocessing=True):
        if data:
            self.run_list_star = data
        if not self.run_list_star:
            print('No list of star-files given, please provide one')
        self.on_time_per_zd = calc_on_time(self.run_list_star,
                                           self.zenith_binning,
                                           self.zenith_labels,
                                           n_chunks=n_chunks,
                                           use_multiprocessing=use_multiprocessing)

        self.total_on_time = np.sum(self.on_time_per_zd)

    def calc_on_off_histo(self, ganymed_file=None):
        select_leaves = ['DataType.fVal', 'MPointingPos.fZd', 'FileId.fVal', 'MTime.fMjd', 'MTime.fTime.fMilliSec',
                         'MTime.fNanoSec', 'MHillas.fSize', 'ThetaSquared.fVal', 'MNewImagePar.fLeakage2']
        if ganymed_file:
            self.ganymed_file_data = ganymed_file

        if not self.ganymed_file_data:
            histos = histos_from_list_of_mars_files(self.run_list_star,
                                                    select_leaves,
                                                    self.zenith_binning,
                                                    self.zenith_labels,
                                                    self.energy_binning,
                                                    self.energy_labels,
                                                    self.theta_square)
        else:
            data_cut = read_mars(self.ganymed_file_data, leaf_names=select_leaves)
            histos = calc_onoffhisto(data_cut, self.zenith_binning, self.zenith_labels, self.energy_binning,
                                     self.energy_labels, self.theta_square)

        # Save Theta-Sqare histograms
        self.theta_square_binning = histos[1][0][1]
        self.on_theta_square_histo = histos[1][0][0]
        self.off_theta_square_histo = histos[1][1][0]

        # Zenith, Energy histograms
        self.on_histo_zenith = histos[0][0]
        self.off_histo_zenith = histos[0][1]

        self.excess_histo = self.on_histo_zenith - self.alpha * self.off_histo_zenith
        self.excess_histo_err = np.sqrt(self.on_histo_zenith + self.alpha**2 * self.off_histo_zenith)

        # Energy histograms

        self.on_histo = np.sum(self.on_histo_zenith, axis=0)
        self.off_histo = np.sum(self.off_histo_zenith, axis=0)

        self.excess_histo = self.on_histo - self.alpha * self.off_histo
        self.excess_histo_err = np.sqrt(self.on_histo + self.alpha**2 * self.off_histo)

        self.significance_histo = li_ma_significance(self.on_histo, self.off_histo, self.alpha)

        # Calculate overall statistics

        self.n_on_events = np.sum(self.on_histo_zenith)
        self.n_off_events = np.sum(self.off_histo_zenith)

        self.n_excess_events = self.n_on_events - self.alpha * self.n_off_events
        self.n_excess_events_err = np.sqrt(self.n_on_events + self.alpha**2 * self.n_off_events)

        self.overall_significance = li_ma_significance(self.n_on_events, self.n_off_events, self.alpha)

    def calc_effective_area(self, analysed_ceres_ganymed=None, ceres_list=None):
        if not ceres_list:
            ceres_list = self.list_of_ceres_files
        if not analysed_ceres_ganymed:
            analysed_ceres_ganymed = self.ganymed_file_mc

        self.effective_area = calc_a_eff_parallel_hd5(self.energy_binning,
                                                      self.zenith_binning,
                                                      self.use_correction_factors,
                                                      self.theta_square,
                                                      path=analysed_ceres_ganymed,
                                                      list_of_hdf_ceres_files=ceres_list)
        return self.effective_area

    def calc_differential_spectrum(self, use_multiprocessing=True):

        if not self.on_time_per_zd:
            self.calc_ontime(use_multiprocessing=use_multiprocessing)

        if not self.on_histo:
            self.calc_on_off_histo()

        if not self.effective_area:
            self.calc_effective_area()

        bin_centers = np.power(10, (np.log10(self.energy_binning[1:]) + np.log10(self.energy_binning[:-1])) / 2)
        bin_width = self.energy_binning[1:] - self.energy_binning[:-1]

        bin_error = np.array([bin_centers - self.energy_binning[:-1], self.energy_binning[1:] - bin_centers])

        self.scaled_effective_area = (self.effective_area * self.on_time_per_zd[:, np.newaxis]) / self.total_on_time
        flux = np.divide(self.excess_histo, np.sum(self.scaled_effective_area, axis=0))
        flux = np.divide(flux, self.total_on_time)
        flux_err = np.ma.divide(np.sqrt(self.on_histo + (1 / 25) * self.off_histo),
                                np.sum(self.scaled_effective_area, axis=0)) / self.total_on_time

        flux_de = np.divide(flux, np.divide(bin_width, 1000))
        flux_de_err = np.divide(flux_err, np.divide(bin_width, 1000))  # / (flux_de * np.log(10))
        flux_de_err_log10 = symmetric_log10_errors(flux_de, flux_de_err)

        self.differential_spectrum = flux_de
        self.differential_spectrum_err = np.ma.array(flux_de_err_log10)

        self.energy_center = bin_centers
        self.energy_error = bin_error

        return flux_de, flux_de_err_log10, bin_centers, bin_error

    ##########################################################
    # Wrapper methods for plotting
    ##########################################################

    def fill_stats(self):
        self.stats["n_on"] = self.n_on_events
        self.stats["n_off"] = self.alpha * self.n_off_events
        self.stats["n_excess"] = self.n_excess_events
        self.stats["on_time_hours"] = self.total_on_time / (60 * 60)
        self.stats["significance"] = self.overall_significance

    def info(self):
        self.fill_stats()
        print(self.stats)

    def plot_flux(self, **kwargs):
        if self.differential_spectrum is None:
            print("No differential spectrum data, please run Spectrum.calc_differential_spectrum()")
            return
        axes = plot_spectrum(self.energy_center,
                             self.energy_error,
                             self.differential_spectrum,
                             self.differential_spectrum_err,
                             self.significance_histo,
                             **kwargs)
        return axes

    def plot_thetasq(self):
        if self.on_theta_square_histo is None:
            print("No theta square histo, please run Spectrum.calc_differential_spectrum()")
            return
        self.fill_stats()
        return plot_theta(self.theta_square_binning,
                          self.on_theta_square_histo,
                          self.off_theta_square_histo,
                          self.theta_square,
                          self.stats)

    ##############################################################
    # Define functions to dump and load variables as json
    ##############################################################

    def save(self, filename):
        data = {}
        for variable_name in self.list_of_variables:
            data[variable_name] = getattr(self, variable_name)

        for entry in data:
            if isinstance(data[entry], (np.ndarray, np.ma.core.MaskedArray)):
                aslist = data[entry].tolist()
                data[entry] = aslist
            elif isinstance(data[entry], dict):
                for element in data[entry]:
                    aslist = data[entry][element].tolist()
                    data[entry][element] = aslist
        with open(filename, 'w') as outfile:
            json.dump(data, outfile)

    def load(self, filename):
        with open(filename) as infile:
            data = json.load(infile)

        for variable_name in data:
            containing = data[variable_name]
            if variable_name in self.list_of_variables:
                if isinstance(containing, list):
                    containing = np.array(containing)
                    if None in containing:  # allows to load masked numpy arrays
                        containing = np.ma.masked_invalid(containing.astype(np.float))
                setattr(self, variable_name, containing)

            else:
                raise KeyError('Key not in list of variables')
