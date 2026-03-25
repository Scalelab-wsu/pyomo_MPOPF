# # Spatial decomposition of IEEE _123_other
IEEE_123_other_area_info = {
    'area1': {
        # Area connection information
        'is_root': True,
        'up_area': [],
        'up_global_node_id': ['1'],
        'up_local_node_id': ['1'],
        'down_areas': ['area2', 'area3'],
        'down_local_node_id': ['D12', 'D13'],
        'down_global_node_id': ['15', '20'],
        'data_dir' : 'area1'
    },
    'area2': {
        # Area connection information
        'is_root': False,
        'up_area': ['area1'],
        'up_global_node_id': ['117'],
        'up_local_node_id': ['D21'],
        'down_areas': ['area4'],
        'down_local_node_id': ['D24'],
        'down_global_node_id': ['62'],
        'data_dir' : 'area2'
    },
    'area3': {
        # Area connection information
        'is_root': False,
        'up_area': ['area1'],
        'up_global_node_id': ['118'],
        'up_local_node_id': ['D31'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area3'

    },
    'area4': {
        # Area connection information
        'is_root': False,
        'up_area': ['area2'],
        'up_global_node_id': ['125'],
        'up_local_node_id': ['D42'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area4'
    }
}

## Spatial decomposition of IEEE_9500
IEEE_9500_area_info = {
    'area1': {
        # Area connection information
        'is_root': True,
        'up_area': [],
        'up_global_node_id': ['1'],
        'up_local_node_id': ['1'],
        'down_areas': ['area2','area3'],
        'down_local_node_id': ['D12','D13'],
        'down_global_node_id': ['21','26'],
        'data_dir' : 'area1'
    },
    'area2': {
        # Area connection information
        'is_root': False,
        'up_area': ['area1'],
        'up_global_node_id': ['22'],
        'up_local_node_id': ['D21'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area2'
    },
    'area3': {
        # Area connection information
        'is_root': False,
        'up_area': ['area1'],
        'up_global_node_id': ['27'],
        'up_local_node_id': ['D31'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area3'

    }
}
## Spatial decomposition of IEEE_9500
test_area_info = {
    'area1': {
        # Area connection information
        'is_root': True,
        'up_area': [],
        'up_global_node_id': ['1'],
        'up_local_node_id': ['1'],
        'down_areas': ['area2','area3'],
        'down_local_node_id': ['D12','D13'],
        'down_global_node_id': ['16','2334'],
        'data_dir' : 'area1'
    },
    'area2': {
        # Area connection information
        'is_root': False,
        'up_area': ['area1'],
        'up_global_node_id': ['17'],
        'up_local_node_id': ['D21'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area2'
    },
    'area3': {
        # Area connection information
        'is_root': False,
        'up_area': ['area1'],
        'up_global_node_id': ['2333'],
        'up_local_node_id': ['D31'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area3'

    }
}