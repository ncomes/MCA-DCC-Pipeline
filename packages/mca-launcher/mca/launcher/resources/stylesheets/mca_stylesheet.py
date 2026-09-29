LAUNCHER_STYLE = """
                    QFrame
                    {
                    background-color: rgba(37,36,37,0);
                    }


                    QPushButton
                    {
                        background-color: rgba(37,36,37,0);
                        color: white
                    }


                    QPushButton::hover
                    {
                        background-color: rgba(33,86,123,1);


                    }

                    QLabel
                    {
                        color: white;
                        background-color: rgba(65,65,64,0);
                    }
                    
                    QLabel#project_name_QLabel
                    {
                        color: rgba(24,26,27,1);
                        background-color: rgba(100,101,100,0);
                        font-family: impact;
                        font-size: 16px;

                    }
                    
                    QComboBox
                    {
                        background-color: rgba(65,65,64,255);
                        color: white;
                    }
                    
                    QLineEdit#path_lineEdit
                    {
                        color: white;
                        border-style: solid;
                        border-width: 2px;
                        border-radius: 9px;
                        border-color: rgba(0,0,0,0.6);
                        background-color: rgba(100,101,100,0.4);
                    }
                    
                    QComboBox#project_comboBox
                    {
                        color: rgba(255,182,0,1);
                        border-style: solid;
                        border-width: 2px;
                        border-radius: 9px;
                        border-color: rgba(0,0,0,0.6);
                        background-color: rgba(100,101,100,0.4);
                        font-family: impact;
                        font-size: 16px;
                    }
                    
                    QComboBox::hover#project_comboBox
                    {
                        background-color: rgba(100,100,100,1);
                    }
                    
                    QPushButton#add_project_pushButton
                    {
                        color: rgba(24,26,27,1);
                        border-style: solid;
                        border-width: 2px;
                        border-radius: 9px;
                        border-color: rgba(0,0,0,0.6);
                        background-color: rgba(100,101,100,0.4);
                        font-family: impact;
                        font-size: 14px;
                    }
                    
                    QPushButton::hover#add_project_pushButton
                    {
                        background-color: rgba(100,100,100,1);
                    }
                    
                    QPushButton::pressed#add_project_pushButton
                    {
                        background-color: rgba(70,70,70,1);
                    }
                    
                    QPushButton#remove_project_pushButton
                    {
                        color: rgba(24,26,27,1);
                        border-style: solid;
                        border-width: 2px;
                        border-radius: 9px;
                        border-color: rgba(0,0,0,0.6);
                        background-color: rgba(100,101,100,0.4);
                        font-family: impact;
                        font-size: 14px;
                    }
                    
                    QPushButton::hover#remove_project_pushButton
                    {
                        background-color: rgba(100,100,100,1);
                    }
                    
                    QPushButton::pressed#remove_project_pushButton
                    {
                        background-color: rgba(70,70,70,1);
                    }
                    
                    QPushButton#update_project_pushButton
                    {
                        color: rgba(24,26,27,1);
                        border-style: solid;
                        border-width: 2px;
                        border-radius: 9px;
                        border-color: rgba(0,0,0,0.6);
                        background-color: rgba(100,101,100,0.4);
                        font-family: impact;
                        font-size: 14px;
                    }
                    
                    QPushButton::hover#update_project_pushButton
                    {
                        background-color: rgba(100,100,100,1);
                    }
                    
                    QPushButton::pressed#update_project_pushButton
                    {
                        background-color: rgba(70,70,70,1);
                    }
                    
                    QPushButton::hover#ue_pushButton
                    {
                        background-color: rgba(70,70,70,1);
                    }
                    QPushButton::pressed#ue_pushButton
                    {
                        background-color: rgba(255,182,0,0.6);
                    }
                    
                    QPushButton::hover#maya_pushButton
                    {
                        background-color: rgba(70,70,70,1);
                    }
                    QPushButton::pressed#maya_pushButton
                    {
                        
                        background-color: rgba(255,182,0,0.6);
                    }
                    
                    QPushButton::hover#mobu_pushButton
                    {
                        background-color: rgba(70,70,70,1);
                    }
                    QPushButton::pressed#mobu_pushButton
                    {
                        
                        background-color: rgba(255,182,0,0.6);
                    }
                    
                    /* The plate everything sits on, and the rows on it. */
                    QFrame#main_frame
                    {
                        border: 6px solid rgba(128,129,129,255);
                        background-color: rgba(37,36,37,255);
                    }

                    QFrame#dcc_row
                    {
                        background-color: rgba(52,52,52,255);
                        border: 1px solid rgba(78,78,78,255);
                        border-radius: 8px;
                    }

                    QLabel#dcc_name
                    {
                        color: white;
                        font-family: impact;
                        font-size: 17px;
                    }

                    QLabel#dcc_detail
                    {
                        color: rgba(168,168,168,255);
                        font-size: 11px;
                    }

                    QPushButton#dcc_action
                    {
                        background-color: rgba(70,70,70,1);
                        color: white;
                        border-radius: 8px;
                        padding: 7px;
                    }

                    QPushButton#dcc_action[mode="install"]
                    {
                        color: rgba(255,182,0,1);
                    }

                    QPushButton::hover#dcc_action
                    {
                        background-color: rgba(255,182,0,0.6);
                    }

                    QPushButton#refresh_pushButton
                    {
                        background-color: rgba(70,70,70,1);
                        color: white;
                        border-radius: 8px;
                        padding: 5px;
                    }

                    QPushButton::hover#refresh_pushButton
                    {
                        background-color: rgba(255,182,0,0.6);
                    }

                    QPushButton::hover#unreal_pushButton
                    {
                        background-color: rgba(70,70,70,1);
                    }

                    QPushButton::pressed#unreal_pushButton
                    {
                        background-color: rgba(255,182,0,0.6);
                    }
                    
                    /* The windows themselves. Without these the stylesheet's white text
                       sits on the system's light background - and it cascades to child
                       windows, so the setup window and the progress window a first run
                       opens were white on white. */
                    QMainWindow, QDialog
                    {
                        background-color: rgba(37,36,37,255);
                    }

                    QMenuBar
                    {
                        background-color: rgba(37,36,37,255);
                        color: white;
                    }

                    QMenuBar::item:selected
                    {
                        background-color: rgba(33,86,123,1);
                    }

                    QMenu
                    {
                        background-color: rgba(52,52,52,255);
                        color: white;
                    }

                    QMenu::item:selected
                    {
                        background-color: rgba(33,86,123,1);
                    }

                    QGroupBox
                    {
                        border: 1px solid rgba(78,78,78,255);
                        border-radius: 8px;
                        margin-top: 12px;
                        padding-top: 10px;
                        color: white;
                    }

                    QGroupBox::title
                    {
                        subcontrol-origin: margin;
                        left: 12px;
                        padding: 0px 4px;
                        color: rgba(255,182,0,1);
                    }

                    QLineEdit
                    {
                        background-color: rgba(65,65,64,255);
                        color: white;
                        border: 1px solid rgba(90,90,90,255);
                        border-radius: 4px;
                        padding: 3px;
                    }

                    QCheckBox
                    {
                        color: white;
                    }

                    /* Styling a QCheckBox at all hands the indicator to the stylesheet, and
                       an unstyled one then draws as an empty box whether it is ticked or
                       not - which on the setup window meant "install the packages now" read
                       as off while it was on. */
                    QCheckBox::indicator
                    {
                        width: 14px;
                        height: 14px;
                        border: 1px solid rgba(120,120,120,255);
                        border-radius: 3px;
                        background-color: rgba(52,52,52,255);
                    }

                    QCheckBox::indicator:checked
                    {
                        border: 1px solid rgba(255,182,0,1);
                        background-color: rgba(255,182,0,1);
                    }

                    QCheckBox::indicator:hover
                    {
                        border: 1px solid rgba(255,182,0,1);
                    }

                    QPlainTextEdit, QTextEdit
                    {
                        background-color: rgba(28,28,28,255);
                        color: rgba(220,220,220,255);
                        border: 1px solid rgba(78,78,78,255);
                    }

                    QProgressBar
                    {
                        background-color: rgba(52,52,52,255);
                        border: 1px solid rgba(78,78,78,255);
                        border-radius: 6px;
                        color: white;
                        text-align: center;
                    }

                    QProgressBar::chunk
                    {
                        background-color: rgba(255,182,0,0.7);
                    }

                    /* Buttons in the setup window, which has no icons to keep clear of. */
                    QMainWindow#setup_window QPushButton
                    {
                        background-color: rgba(70,70,70,255);
                        color: white;
                        border-radius: 6px;
                        padding: 5px 10px;
                    }

                    QMainWindow#setup_window QPushButton::hover
                    {
                        background-color: rgba(255,182,0,0.6);
                    }
                    """
