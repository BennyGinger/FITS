from typing import Any


dev_settings: dict[str, Any] = {
    
    'user_name': 'test_user',
    'run_dir': '/path/to/images',
    
    'runtime': {'log_dir': None,
                'mode': 'cli',
                'dry_run': False,
                'console_level': 'info',
                'file_level': 'debug'
                },
    
    'convert': {'enabled': True, 
                'params': {'channel_labels': ['DAPI', 'FITC', 'TRITC'],
                            'export_channels': ['DAPI', 'FITC'],
                            'user_defined_metadata': {'Experimenter': 'Dr. Smith', 'Date': '2024-06-15'},
                            'compression': 'zlib',
                            'overwrite': True,
                            'z_projection': 'max'}},

}