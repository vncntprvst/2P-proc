function h = warndlg(msg, varargin)
% Headless replacement for MATLAB's warndlg (CellReg calls it from align_images): print the
% warning and continue, as the GUI does after the dialog is dismissed.
warning('CellReg:warndlg', '%s', msg);
h = [];
end
