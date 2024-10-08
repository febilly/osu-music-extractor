import io
import shutil
import tkinter
from tkinter import filedialog
from pathlib import Path
import zipfile
import eyed3
from tqdm import tqdm
# from rich import print
from dataclasses import dataclass
import logging

PUT_TITLE_BEFORE_ARTIST = True

invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
substitute_char = '-'

songs_counter = 0

logging.getLogger().setLevel(logging.ERROR)

@dataclass
class Song:
    path: Path
    title: str
    artist: str
    filename: str

def get_section(osu_path: Path, section: str) -> dict[str, str]:
    """
    Get a section from a .osu file.
    """
    with osu_path.open('r', encoding='utf-8') as f:
        lines = f.readlines()
    lines = [line for line in lines if line.strip()]
    
    metadata: dict[str, str] = {}
    in_section = False
    for line in lines:
        if line.startswith(section):
            in_section = True
            continue
        if in_section:
            if line.startswith('['):
                break
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip()

    return metadata

def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by replacing invalid characters with a substitute character.
    """
    for char in invalid_chars:
        filename = filename.replace(char, substitute_char)
    
    return filename

def analyse_folder(folder: Path) -> Song | None:
    """
    Analyse a beatmap folder and return a Song object if the folder contains a valid song.
    """
    file_paths: list[Path] = []
    for file in folder.iterdir():
        if file.is_file():
            file_paths.append(file)
            
    osu_file = None
    for file in file_paths:
        if file.suffix == '.osu':
            osu_file = file
            break
    
    if not osu_file:
        return None
    
    general = get_section(osu_file, '[General]')
    metadata = get_section(osu_file, '[Metadata]')
    
    audiofile = folder / general['AudioFilename']
    if not audiofile.exists():
        return None
    
    if PUT_TITLE_BEFORE_ARTIST:
        filename = f'{metadata['Title']} - {metadata['Artist']}.mp3'
    else:
        filename = f'{metadata['Artist']} - {metadata['Title']}.mp3'
    filename = sanitize_filename(filename)
    
    song = Song(
        path=audiofile,
        title=metadata['TitleUnicode'] if 'TitleUnicode' in metadata else metadata['Title'],
        artist=metadata['ArtistUnicode'] if 'ArtistUnicode' in metadata else metadata['Artist'],
        filename=filename
    )
    
    return song

def has_metadata(file: Path) -> bool:
    """
    Check if a mp3 file has metadata.
    assumes that the file is a valid mp3 file.
    """
    audiofile = eyed3.load(file)
    assert audiofile is not None
    tag = audiofile.tag
    
    return tag is not None and tag.artist and tag.title

def is_valid_mp3(file: Path) -> bool:
    """
    Check if a file is a valid mp3 file.
    """
    try:
        audiofile = eyed3.load(file)
        return audiofile is not None and audiofile.info is not None
    except Exception:
        return False

def write_song(song: Song, outputdir: Path):
    """
    Write a song to the output directory.
    it checks the validity of the mp3 file and writes the metadata.
    it also renames ogg files back to mp3.
    """
    global songs_counter
    
    outputpath = outputdir / song.filename
    
    if outputpath.exists():
        return
    
    # shutil.copy(song.path, outputpath)
    outputpath.write_bytes(song.path.read_bytes())
    songs_counter += 1
    
    if not is_valid_mp3(outputpath):  # some 'mp3' files are actually other formats
        with open(outputpath, 'rb') as f:
            header = f.read(4)
            
        if header == b'OggS':  # the most common actual format
            new_outputpath = outputpath.with_suffix('.ogg')
            shutil.move(outputpath, new_outputpath)
            print(f"\nRenamed {outputpath.name} to {new_outputpath.name} since it's actually an ogg file.")
        else:
            print(f"\nWarning: {outputpath.name} is not a valid mp3 file.")
        
        return
        
    # if has_metadata(outputpath):
    #     return
    
    audiofile = eyed3.load(outputpath)
    assert audiofile is not None
    if audiofile.tag is None:  # make sure the mp3 file have a tag
        audiofile.initTag()
    
    # write metadata
    tag = audiofile.tag
    assert tag is not None
    tag.artist = song.artist
    tag.title = song.title
    
    try:  # eyed3 don't support ID3 v2.2 so we just ignore it
        tag.save(encoding='utf-8')
    except NotImplementedError:
        pass

def process_beatmap_folder(folder: Path, outputdir: Path):
    """
    Analyse the folder and write the song if it contains one.
    """
    result = analyse_folder(folder)
    if result:
        write_song(result, outputdir)

def process_catalog_directory(directory: Path, outputdir: Path):
    """
    process the directory that contains the beatmap folders.
    """
    paths_to_scan = []
    
    for path in directory.iterdir():
        if path.is_dir():
            paths_to_scan.append(path)
        elif path.suffix == '.osz':
            paths_to_scan.append(zipfile.Path(path))
            
    print("Processing individual beatmaps...")
    for path in tqdm(paths_to_scan):
        process_beatmap_folder(path, outputdir)

def process_pack(pack: Path, outputdir: Path):
    """
    Process a .zip file that contains serveral .osz files.
    """
    compressed_osz_paths: list[zipfile.Path] = []
    
    zipfile_path = zipfile.Path(pack)
    for path in zipfile_path.iterdir():
        if path.suffix == '.osz':
            compressed_osz_paths.append(path)
            
    for compressed_osz_path in compressed_osz_paths:
        osz_data = compressed_osz_path.read_bytes()
        osz_bytes = io.BytesIO(osz_data)
        inner_path = zipfile.Path(osz_bytes)
        
        process_beatmap_folder(inner_path, outputdir)
            
        del osz_bytes
        del osz_data

def process_everything(inputdir: Path, outputdir: Path):
    """
    Process everything (beatmap folders, .osz files, and beatmap packs) in inputdir.
    """
    process_catalog_directory(inputdir, outputdir)
    
    potential_packs = []
    for path in inputdir.iterdir():
        if path.suffix == '.zip':
            potential_packs.append(path)

    print("Processing beatmap packs...")
    for pack in tqdm(potential_packs):
        process_pack(pack, outputdir)

def ask_quit():
    print("Press Enter to exit.")
    input()
    exit()

def ask_for_directories() -> tuple[Path, Path]:
    """
    Ask the user for the input and output directories.
    """
    root = tkinter.Tk()
    root.withdraw()

    inputdir = filedialog.askdirectory(
        title="Select the \"Songs\" Folder.", initialdir=str(Path.home() / "AppData/Local/osu!/Songs"))
    if not inputdir:
        exit()

    outputdir = filedialog.askdirectory(title="Select a output Folder.")
    if not outputdir:
        exit()

    return Path(inputdir), Path(outputdir)

def main():
    global songs_counter
    
    inputdir, outputdir = ask_for_directories()

    if inputdir == outputdir:
        print("Input and output directory can't be the same.")
        ask_quit()

    print(f"Inputdir:  {inputdir}")
    print(f"Outputdir: {outputdir}")
    print("Press Enter to start, or close this window to cancel.")
    input()

    process_everything(inputdir, outputdir)

    print(f"\nDone. {songs_counter} songs extracted.")
    ask_quit()

if __name__ == "__main__":
    main()
