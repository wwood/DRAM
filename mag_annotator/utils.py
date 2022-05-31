import re
import subprocess
from collections import Counter
from os import path
from urllib.request import urlopen, urlretrieve
from urllib.error import HTTPError
import pandas as pd
import logging


def download_file(url, logger, output_file=None, verbose=True):
    # TODO: catching error 4 and give error message to retry or retry automatically
    if verbose:
        print('downloading %s' % url)
    if output_file is None:
        return urlopen(url).read().decode('utf-8')
    else:
        try:
            urlretrieve(url, output_file)
        except HTTPError as error:
            logger.critical(f"Something went wrong with the download of the url: {url}")
            raise error
        # run_process(['wget', '-O', output_file, url], verbose=verbose)


def setup_logger(logger, *log_file_paths, level=logging.INFO):
    logger.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    # create console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    # create formatter and add it to the handlers
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    for log_file_path in log_file_paths:
        fh = logging.FileHandler(log_file_path)
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
    # add the handlers to the logger
    logger.addHandler(fh)


def run_process(command, logger, shell:bool=False, capture_stdout:bool=True, save_output:str=None, 
                check:bool=False, stop_on_error:bool=True, verbose:bool=False) -> str:
    """
    Standardization of parameters for using subprocess.run, provides verbose mode and option to run via shell
    """
    # TODO just remove check
    try:
        results = subprocess.run(command, check=check, shell=shell,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as error:
        logger.critical(f'The subcommand {command} experienced an error')
        if stop_on_error:
            raise error
    if results.returncode != 0:
        logger.critical(f'The subcommand {command} experienced an error: {results.stderr}')
        logging.debug(results.stdout)
        if stop_on_error:
           raise subprocess.SubprocessError(f"The subcommand {' '.join(command)} experienced an error, see the log for more info.")

    if save_output is not None:
        with open(save_output, 'w') as out:
            out.write(results.stdout)

    if capture_stdout:
        return results.stdout


def make_mmseqs_db(fasta_loc, output_loc, logger, create_index=True, threads=10, verbose=False):
    """Takes a fasta file and makes a mmseqs2 database for use in blast searching and hmm searching with mmseqs2"""
    run_process(['mmseqs', 'createdb', fasta_loc, output_loc], logger, verbose=verbose)
    if create_index:
        tmp_dir = path.join(path.dirname(output_loc), 'tmp')
        run_process(['mmseqs', 'createindex', output_loc, tmp_dir, '--threads', str(threads)], logger, verbose=verbose)


def multigrep(search_terms, search_against, logger, split_char='\n', output='.'):
    # TODO: multiprocess this over the list of search terms
    """Search a list of exact substrings against a database, takes name of mmseqs db index with _h to search against"""
    hits_file = path.join(output, 'hits.txt')
    with open(hits_file, 'w') as f:
        f.write('%s\n' % '\n'.join(search_terms))
    results = run_process(['grep', '-a', '-F', '-f', hits_file, search_against], logger, capture_stdout=True, verbose=False)
    processed_results = [i.strip() for i in results.strip().split(split_char)
                         if len(i) > 0]
    # remove(hits_file)
    return {i.split()[0]: i for i in processed_results if i != ''}


def merge_files(files_to_merge, outfile, has_header=False):
    """It's in the name, if has_header assumes all files have the same header"""
    with open(outfile, 'w') as outfile_handle:
        if has_header:
            outfile_handle.write(open(files_to_merge[0]).readline())
        for file in files_to_merge:
            with open(file) as f:
                if has_header:
                    _ = f.readline()
                outfile_handle.write(f.read())


def get_ids_from_annotation(frame):
    id_list = list()
    # get kegg gene ids
    if 'kegg_genes_id' in frame:
        id_list += [j.strip() for i in frame.kegg_genes_id.dropna() for j in i.split(',')]
    # get kegg orthology ids
    if 'ko_id' in frame:
        id_list += [j.strip() for i in frame.ko_id.dropna() for j in i.split(',')]
    # Get old ko numbers
    # TODO Get rid of this old stuff
    if 'kegg_id' in frame:
        id_list += [j.strip() for i in frame.kegg_id.dropna() for j in i.split(',')]
    # get kegg ec numbers
    if 'kegg_hit' in frame:
        for kegg_hit in frame.kegg_hit.dropna():
            id_list += [i[1:-1] for i in re.findall(r'\[EC:\d*.\d*.\d*.\d*\]', kegg_hit)]
    # get merops ids
    if 'peptidase_family' in frame:
        id_list += [j.strip() for i in frame.peptidase_family.dropna() for j in i.split(';')]
    # get cazy ids
    if 'cazy_id' in frame:
        id_list += [j for i in frame.cazy_id.dropna() for j in set([k.split('_')[0] for k in i.split('; ')])]
    # get cazy ec numbers
    if 'cazy_hits' in frame:
        id_list += [f"{j[1:3]}:{j[4:-1]}" for i in frame.cazy_hits.dropna()
                    for j in re.findall(r'\(EC [\d+\.]+[\d-]\)', i)]
        # get cazy ec numbers from old format
        # TODO Don't have this in DRAM 2
        for cazy_hit in frame.cazy_hits.dropna():
            id_list += [i[1:-1].split('_')[0] for i in re.findall(r'\[[A-Z]*\d*?\]', cazy_hit)]
    # get pfam ids
    if 'pfam_hits' in frame:
        id_list += [j[1:-1].split('.')[0] for i in frame.pfam_hits.dropna()
                    for j in re.findall(r'\[PF\d\d\d\d\d.\d*\]', i)]
    return Counter(id_list)


#TODO unify this with get_ids_from_annotation
def get_ids_from_row(row):
    id_list = list()
    # get kegg gene ids
    if 'kegg_genes_id' in row and not pd.isna(row['kegg_genes_id']):
        id_list += row['kegg_genes_id']
    # get kegg orthology ids
    if 'ko_id' in row and not pd.isna(row['ko_id']):
        id_list += [j for j in row['ko_id'].split(',')]
    # Get old ko numbers
    # TODO Get rid of this old stuff
    if 'kegg_id' in row and not pd.isna(row['kegg_id']):
        id_list += [j for j in row['kegg_id'].split(',')]
    # get ec numbers
    if 'kegg_hit' in row and not pd.isna(row['kegg_hit']):
        id_list += [i[1:-1] for i in re.findall(r'\[EC:\d*.\d*.\d*.\d*\]', row['kegg_hit'])]
    # get merops ids
    if 'peptidase_family' in row and not pd.isna(row['peptidase_family']):
        id_list += [j for j in row['peptidase_family'].split(';')]
    # get cazy ids
    if 'cazy_id' in row and not pd.isna(row['cazy_id']):
        id_list += [j.split('_')[0] for i in row[cazy_id] for j in i.split('; ')]
    if 'cazy_hits' in row and not pd.isna(row['cazy_hits']):
        id_list += [i[1:-1].split('_')[0] for i in re.findall(r'\[[A-Z]*\d*?\]', row['cazy_hits'])]
        for cazy_hit in frame.cazy_hits.dropna():
            id_list += [i[1:-1].split('_')[0] for i in re.findall(r'\[[A-Z]*\d*?\]', cazy_hit)]
    # get pfam ids
    if 'pfam_hits' in row and not pd.isna(row['pfam_hits']):
        id_list += [j[1:-1].split('.')[0]
                    for j in re.findall(r'\[PF\d\d\d\d\d.\d*\]', row['pfam_hits'])]
    return set(id_list)


def divide_chunks(l, n):
    # looping till length l
    for i in range(0, len(l), n):
        yield l[i:i + n]


def remove_prefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text  # or whatever


def remove_suffix(text, suffix):
    if text.endswith(suffix):
        return text[:-1*len(suffix)]
    return text  # or whatever


def get_ordered_uniques(seq):
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x) or pd.isna(x))]
