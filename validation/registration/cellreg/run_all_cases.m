function run_all_cases(inputs_dir, outputs_dir, cellreg_dir, microns_per_pixel, case_index)
% Run CellReg on every case folder in inputs_dir, with rigid ('Translations and
% Rotations') and 'Non-rigid' alignment. One failure does not stop the others;
% errors are written next to the outputs.

addpath(genpath(cellreg_dir));
addpath(fileparts(mfilename('fullpath')), '-begin');  % headless warndlg shim before MATLAB's
if ~exist(outputs_dir, 'dir'); mkdir(outputs_dir); end
if ~isempty(ver('parallel'))
    parpool('local', str2double(getenv('SLURM_CPUS_ON_NODE')));
end
cases = dir(inputs_dir);
cases = cases([cases.isdir] & ~startsWith({cases.name}, '.'));
if nargin > 4 && ~isempty(case_index)  % one case per SLURM array task (0-based)
    cases = cases(case_index + 1);
end
modes = {'Translations and Rotations', 'Non-rigid'};
tags = {'rigid', 'nonrigid'};
for c = 1:numel(cases)
    for m = 1:numel(modes)
        out_file = fullfile(outputs_dir, sprintf('%s__cellreg_%s.mat', cases(c).name, tags{m}));
        if exist(out_file, 'file'); continue; end
        fprintf('%s | %s\n', cases(c).name, modes{m});
        t = tic;
        try
            run_cellreg_case(fullfile(inputs_dir, cases(c).name), modes{m}, out_file, microns_per_pixel);
            fprintf('  done in %.0f s\n', toc(t));
        catch ME
            fprintf('  FAILED: %s\n', ME.message);
            fid = fopen([out_file(1:end-4) '_error.txt'], 'w');
            fprintf(fid, '%s', getReport(ME, 'extended', 'hyperlinks', 'off'));
            fclose(fid);
        end
    end
end
delete(gcp('nocreate'));
end
